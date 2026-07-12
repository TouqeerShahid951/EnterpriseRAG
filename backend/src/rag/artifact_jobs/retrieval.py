"""Plan-driven, ABAC-constrained evidence retrieval."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import re

from ..auth.abac import build_abac_filter
from ..auth.context import UserContext
from ..auth.document_access import can_read_document
from ..core.config import Settings
from ..query.qdrant import QdrantClient, SearchHit
from ..query.state import initial_state
from ..query.query_retrieval import (
    add_document_scope,
    add_expiry_scope,
    retrieve_candidates,
)
from ..query.reranker import rerank_hits
from ..query.intent_router import route_query
from ..query.sources import dedupe_hits
from ..query.temporal import add_effective_date_scope, target_date_for_query
from ..repositories.document_models import DocumentRecord, DocumentRepository
from ..query.rag_config_models import RagConfigRecord
from ..schemas.query import QueryRequest
from .contracts import (
    DocumentPlan,
    DocumentPlanSection,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceSection,
)
from .job_models import ArtifactJobRecord


SELECTED_DOCUMENT_SCAN_LIMIT = 4000
INFERRED_DOCUMENT_SCOPE_LIMIT = 100
SCOPE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
SCOPE_STOP_TOKENS = {
    "about",
    "all",
    "artifact",
    "complete",
    "comprehensive",
    "create",
    "deck",
    "detail",
    "detailed",
    "details",
    "doc",
    "docs",
    "docx",
    "document",
    "documents",
    "file",
    "files",
    "for",
    "from",
    "generate",
    "in",
    "list",
    "make",
    "pdf",
    "pptx",
    "presentation",
    "report",
    "slides",
    "summarize",
    "summary",
    "the",
    "with",
}


def retrieve_document_evidence(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    *,
    inference: object,
    qdrant: QdrantClient,
    config: Settings,
    rag_config: RagConfigRecord,
    document_repo: DocumentRepository | None = None,
) -> EvidenceManifest:
    user = UserContext(
        user_id=job.user_id,
        email=job.user_email,
        account_type=job.account_type,  # type: ignore[arg-type]
        group_paths=job.group_paths,
        clearance_level=job.clearance_level,
        permission_version=job.permission_version,
    )
    scoped_job = _with_inferred_document_scope(job, plan, user=user, document_repo=document_repo)
    sections = [
        _retrieve_section(
            scoped_job,
            section,
            user=user,
            inference=inference,
            qdrant=qdrant,
            config=config,
            rag_config=rag_config,
        )
        for section in plan.sections
    ]
    if any(section.coverage_status in {"none", "partial"} for section in sections):
        sections = [
            _retry_section(
                scoped_job,
                plan_section,
                current,
                user=user,
                inference=inference,
                qdrant=qdrant,
                config=config,
                rag_config=rag_config,
            )
            if current.coverage_status in {"none", "partial"}
            else current
            for plan_section, current in zip(plan.sections, sections, strict=True)
        ]
        rounds = 2
    else:
        rounds = 1
    return EvidenceManifest(sections=sections, retrieval_rounds=rounds)


def _retrieve_section(
    job: ArtifactJobRecord,
    section: DocumentPlanSection,
    *,
    user: UserContext,
    inference: object,
    qdrant: QdrantClient,
    config: Settings,
    rag_config: RagConfigRecord,
) -> EvidenceSection:
    hits: list[SearchHit] = []
    scan_hits: list[SearchHit] = []
    top_k_hits: list[SearchHit] = []
    scanned = False
    scan_limit = 0
    if section.retrieval_mode in {"document_scan", "structured_rows"} and job.document_ids:
        qdrant_filter = _authorized_filter(job, user, query=" ".join(section.retrieval_queries))
        scan_limit = SELECTED_DOCUMENT_SCAN_LIMIT
        scan_hits = qdrant.retrieve_document_chunks(
            document_ids=list(job.document_ids),
            qdrant_filter=qdrant_filter,
            structured_only=section.retrieval_mode == "structured_rows",
            limit=scan_limit,
        )
        scanned = True
        hits.extend(scan_hits)
    for query in section.retrieval_queries:
        query_hits = _retrieve_query(
            job,
            query,
            user=user,
            inference=inference,
            qdrant=qdrant,
            config=config,
            rag_config=rag_config,
        )
        top_k_hits.extend(query_hits)
        hits.extend(query_hits)
    deduped = dedupe_hits(hits)
    scanned_doc_ids = {
        str(hit.payload.get("doc_id") or hit.point_id)
        for hit in scan_hits
    }
    return _evidence_section(
        section,
        deduped,
        scanned=scanned,
        searched_query_count=len(section.retrieval_queries),
        scanned_document_count=len(scanned_doc_ids),
        scanned_chunk_count=len(scan_hits),
        top_k_record_count=len(dedupe_hits(top_k_hits)),
        scan_limit_reached=bool(scan_limit and len(scan_hits) >= scan_limit),
        scope_scan_without_selected_docs=section.retrieval_mode == "structured_rows" and scanned and not job.document_ids,
    )


def _with_inferred_document_scope(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    *,
    user: UserContext,
    document_repo: DocumentRepository | None,
) -> ArtifactJobRecord:
    if job.document_ids or document_repo is None:
        return job
    document_ids = _infer_document_scope(job, plan, user=user, document_repo=document_repo)
    if not document_ids:
        return job
    return replace(job, document_ids=tuple(document_ids))


def _infer_document_scope(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    *,
    user: UserContext,
    document_repo: DocumentRepository,
) -> list[str]:
    scope_terms = _requested_document_scope_terms(job, plan)
    if not scope_terms:
        return []
    matches: list[DocumentRecord] = []
    for document in document_repo.list_documents():
        if document.ingest_status != "complete" or not document.is_current:
            continue
        if job.group_path and document.group_path != job.group_path:
            continue
        if not can_read_document(user, document):  # type: ignore[arg-type]
            continue
        if _document_matches_scope_terms(document, scope_terms):
            matches.append(document)
    return [document.id for document in matches[:INFERRED_DOCUMENT_SCOPE_LIMIT]]


def _requested_document_scope_terms(job: ArtifactJobRecord, plan: DocumentPlan) -> list[str]:
    text = " ".join([
        job.original_request,
        plan.title,
        plan.purpose,
        *[query for section in plan.sections for query in section.retrieval_queries],
    ])
    return sorted(_scope_tokens(text))


def _document_matches_scope_terms(document: DocumentRecord, scope_terms: list[str]) -> bool:
    return bool(set(scope_terms) & _document_scope_tokens(document))


def _document_scope_tokens(document: DocumentRecord) -> set[str]:
    return _scope_tokens(_document_identity_text(document))


def _document_identity_text(document: DocumentRecord) -> str:
    values = [document.title, document.source_id, document.file_path]
    return " ".join(str(value).lower() for value in values if value)


def _scope_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in SCOPE_TOKEN_RE.finditer(text):
        token = _normalize_scope_token(match.group(0))
        if token and token not in SCOPE_STOP_TOKENS:
            tokens.add(token)
    return tokens


def _normalize_scope_token(token: str) -> str:
    normalized = token.lower()
    if normalized.isdigit() or len(normalized) < 3:
        return ""
    if normalized.endswith("ies") and len(normalized) > 4:
        normalized = normalized[:-3] + "y"
    elif normalized.endswith("s") and len(normalized) > 3:
        normalized = normalized[:-1]
    return normalized


def _retry_section(
    job: ArtifactJobRecord,
    section: DocumentPlanSection,
    current: EvidenceSection,
    *,
    user: UserContext,
    inference: object,
    qdrant: QdrantClient,
    config: Settings,
    rag_config: RagConfigRecord,
) -> EvidenceSection:
    query = f"{section.objective}. Original request: {job.original_request}"
    retry_hits = _retrieve_query(
        job,
        query,
        user=user,
        inference=inference,
        qdrant=qdrant,
        config=config,
        rag_config=rag_config,
    )
    existing = [_record_as_hit(record) for record in current.records]
    updated = _evidence_section(
        section,
        dedupe_hits([*existing, *retry_hits]),
        scanned=current.coverage_status == "complete_scan",
        searched_query_count=current.searched_query_count + 1,
        scanned_document_count=current.scanned_document_count,
        scanned_chunk_count=current.scanned_chunk_count,
        top_k_record_count=current.top_k_record_count + len(dedupe_hits(retry_hits)),
        scan_limit_reached=False,
        scope_scan_without_selected_docs=False,
    )
    return updated.model_copy(update={"warnings": list(dict.fromkeys([*current.warnings, *updated.warnings]))})


def _retrieve_query(
    job: ArtifactJobRecord,
    query: str,
    *,
    user: UserContext,
    inference: object,
    qdrant: QdrantClient,
    config: Settings,
    rag_config: RagConfigRecord,
) -> list[SearchHit]:
    request = QueryRequest(
        query=query,
        session_id=job.session_id,
        group_path=job.group_path,
        document_ids=list(job.document_ids),
    )
    ctx = initial_state(
        trace_id=job.trace_id,
        session_id=job.session_id,
        request=request,
        user=user,
        started=0.0,
        token_budget=rag_config.retrieval_token_budget,
    )
    route_plan, _signals = route_query(
        query,
        turns=[],
        base_top_k=max(config.rag_top_k, 8),
        llm_verifier=None,
        verifier_model=None,
        verifier_enabled=False,
    )
    ctx["route_plan"] = route_plan
    ctx["intent"] = route_plan.public_intent
    ctx["sub_queries"] = [query]
    ctx["is_current_only"] = target_date_for_query(query) is None
    hits = retrieve_candidates(ctx, config=config, ollama=inference, qdrant=qdrant)  # type: ignore[arg-type]
    max_candidates = min(config.rag_reranker_max_candidates, config.artifact_reranker_max_candidates)
    return rerank_hits(
        query,
        hits,
        top_k=min(max(route_plan.top_k, 8), max_candidates),
        max_candidates=max_candidates,
        model_name=rag_config.reranker_model,
        cache_dir=config.rag_reranker_cache_dir,
    )


def _authorized_filter(job: ArtifactJobRecord, user: UserContext, *, query: str) -> dict[str, object]:
    current_only = target_date_for_query(query) is None
    qdrant_filter = build_abac_filter(user, is_current_only=current_only)
    qdrant_filter = add_effective_date_scope(
        qdrant_filter,
        target_date_for_query(query) if not current_only else None,
    )
    qdrant_filter = add_expiry_scope(qdrant_filter)
    return add_document_scope(qdrant_filter, list(job.document_ids))


def _evidence_section(
    section: DocumentPlanSection,
    hits: list[SearchHit],
    *,
    scanned: bool,
    searched_query_count: int,
    scanned_document_count: int,
    scanned_chunk_count: int,
    top_k_record_count: int,
    scan_limit_reached: bool,
    scope_scan_without_selected_docs: bool,
) -> EvidenceSection:
    records = [
        _record_from_hit(hit, section_title=section.title, query=" | ".join(section.retrieval_queries))
        for hit in hits
        if str(hit.payload.get("text") or "").strip() or hit.payload.get("structured_fields")
    ]
    warnings: list[str] = []
    if scanned and not scan_limit_reached:
        status = "complete_scan"
        if scope_scan_without_selected_docs:
            warnings.append("Structured rows were scanned across the authorized Knowledge Space scope.")
    elif scanned and scan_limit_reached:
        status = "partial" if records else "none"
        warnings.append("Authorized scan reached the safety limit; coverage must not be described as exhaustive.")
    elif records and section.retrieval_mode in {"document_scan", "structured_rows"}:
        status = "partial"
        warnings.append("Exhaustive coverage was requested but no selected-document scan was available.")
    elif records:
        status = "sufficient"
        warnings.append("Coverage is based on top-k retrieval, not an exhaustive scan.")
    else:
        status = "none"
        warnings.append("No authorized evidence was found for this section.")
    if section.coverage_requirement.startswith("complete") and not scanned:
        status = "partial" if records else "none"
        warnings.append("Coverage is retrieval-based and must not be described as exhaustive.")
    return EvidenceSection(
        title=section.title,
        objective=section.objective,
        retrieval_mode=section.retrieval_mode,
        coverage_requirement=section.coverage_requirement,
        coverage_status=status,  # type: ignore[arg-type]
        records=records,
        warnings=list(dict.fromkeys(warnings)),
        searched_query_count=searched_query_count,
        scanned_document_count=scanned_document_count,
        scanned_chunk_count=scanned_chunk_count,
        top_k_record_count=top_k_record_count,
    )


def _record_from_hit(hit: SearchHit, *, section_title: str, query: str) -> EvidenceRecord:
    payload = hit.payload
    doc_id = str(payload.get("doc_id") or hit.point_id)
    chunk_id = str(payload.get("chunk_id") or hit.point_id)
    raw_fields = payload.get("structured_fields")
    fields = {
        str(item.get("label")): str(item.get("value"))
        for item in raw_fields
        if isinstance(item, dict) and item.get("label") and item.get("value")
    } if isinstance(raw_fields, list) else {}
    return EvidenceRecord(
        evidence_id=_evidence_id(doc_id, chunk_id),
        section_title=section_title,
        query=query,
        doc_id=doc_id,
        doc_title=str(payload.get("doc_title") or "Untitled"),
        chunk_id=chunk_id,
        page_start=_int(payload.get("page_start")) or _int(payload.get("page")),
        page_end=_int(payload.get("page_end")) or _int(payload.get("page_start")) or _int(payload.get("page")),
        content_type=str(payload.get("chunk_type") or payload.get("structured_kind") or "text"),
        text=str(payload.get("text") or ""),
        structured_fields=fields,
        retrieval_score=float(hit.score),
        rerank_score=float(payload["_rerank_score"]) if isinstance(payload.get("_rerank_score"), int | float) else None,
    )


def _record_as_hit(record: EvidenceRecord) -> SearchHit:
    return SearchHit(
        point_id=record.chunk_id,
        score=record.retrieval_score,
        payload={
            "doc_id": record.doc_id,
            "doc_title": record.doc_title,
            "chunk_id": record.chunk_id,
            "page_start": record.page_start,
            "page_end": record.page_end,
            "chunk_type": record.content_type,
            "text": record.text,
            "structured_fields": [
                {"label": label, "value": value}
                for label, value in record.structured_fields.items()
            ],
            "_rerank_score": record.rerank_score,
        },
    )


def _evidence_id(doc_id: str, chunk_id: str) -> str:
    return "ev_" + sha256(f"{doc_id}:{chunk_id}".encode("utf-8")).hexdigest()[:20]


def _int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None
