"""Evidence diagnostics built from the retrieval trace of an evaluation case."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
import unicodedata

from ...documents.models import DocumentRecord, DocumentRepository
from rag.query.retrieval.retrieval_trace import (
    RetrievalTraceCandidate,
    RetrievalStageName,
    RetrievalTrace,
    RetrievalTraceStage,
)
from rag.evaluations.schemas import EvaluationCase, EvaluationEvidenceExpectation

_EVIDENCE_STAGE_NAMES: tuple[RetrievalStageName, ...] = (
    "retrieved",
    "rerank_input",
    "reranked",
    "final_evidence",
)
_ANCHOR_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class _ResolvedEvidenceExpectation:
    index: int
    expectation: EvaluationEvidenceExpectation
    document: DocumentRecord | None
    resolution_status: str


def build_diagnostic(
    case: EvaluationCase,
    *,
    trace: RetrievalTrace,
    document_repo: DocumentRepository,
    reranker_model: str | None,
) -> dict[str, Any]:
    current_documents = _current_complete_documents(document_repo)
    indexed_titles, missing_titles = _indexed_expected_docs(
        case, documents=current_documents
    )
    retrieved = trace.latest("retrieved")
    rerank_input = trace.latest("rerank_input")
    reranked = trace.latest("reranked")
    post_policy = trace.latest("post_policy")
    final_evidence = trace.latest("final_evidence")
    retrieved_rows = _trace_rows(retrieved)
    rerank_input_rows = _trace_rows(rerank_input)
    reranked_rows = _trace_rows(reranked)
    post_policy_rows = _trace_rows(post_policy)
    final_evidence_rows = _trace_rows(final_evidence)
    retrieved_union_rows = _trace_union_rows(trace, "retrieved")
    retrieved_titles = [str(row.get("doc_title") or "") for row in retrieved_rows]
    reranked_titles = [str(row.get("doc_title") or "") for row in reranked_rows]
    retrieved_union_titles = list(
        dict.fromkeys(str(row.get("doc_title") or "") for row in retrieved_union_rows)
    )
    retrieved_pages = sorted(
        {page for row in retrieved_rows if (page := _row_page(row)) is not None}
    )
    evidence_expectations = _evidence_expectation_diagnostic(
        case.evidence_expectations,
        trace=trace,
        documents=current_documents,
    )
    legacy_page_expectation = _legacy_page_expectation_diagnostic(
        case,
        retrieved_rows=retrieved_union_rows,
        documents=current_documents,
    )
    serialized_trace = [
        {
            "name": stage.name,
            "attempt": stage.attempt,
            "status": stage.status,
            "candidate_count": len(stage.candidates),
            "candidates": [candidate.to_row() for candidate in stage.candidates],
        }
        for stage in trace.stages
    ]
    return {
        "status": "ok",
        "trace_schema_version": 2,
        "top_k": len(retrieved_rows),
        "indexed_source_docs": indexed_titles,
        "missing_indexed_source_docs": missing_titles,
        "expected_docs_indexed": not missing_titles,
        "retrieved_source_docs": retrieved_titles,
        "retrieved_union_source_docs": retrieved_union_titles,
        "reranked_source_docs": reranked_titles,
        "retrieved_pages": retrieved_pages,
        "retrieval_candidates": retrieved_rows,
        "hits": retrieved_rows,
        "rerank_input_candidates": rerank_input_rows,
        "reranked_candidates": reranked_rows,
        "post_policy_candidates": post_policy_rows,
        "final_evidence_candidates": final_evidence_rows,
        "retrieval_trace": serialized_trace,
        "trace_stages": [
            {
                "name": stage["name"],
                "attempt": stage["attempt"],
                "status": stage["status"],
                "candidate_count": stage["candidate_count"],
            }
            for stage in serialized_trace
        ],
        "reranker_model": reranker_model,
        "reranker_top_k": len(reranked_rows),
        "reranker_max_candidates": len(rerank_input_rows),
        "evidence_expectations": evidence_expectations,
        "legacy_page_expectation": legacy_page_expectation,
        "expected_docs_retrieved": _expected_docs_retrieved(
            case.expected_source_docs, retrieved_union_titles
        ),
        "expected_pages_retrieved": legacy_page_expectation["passed"],
    }


def _trace_rows(stage: RetrievalTraceStage | None) -> list[dict[str, Any]]:
    if stage is None:
        return []
    return [candidate.to_row() for candidate in stage.candidates]


def _trace_union_rows(
    trace: RetrievalTrace, name: RetrievalStageName
) -> list[dict[str, Any]]:
    return [candidate.to_row() for candidate in _trace_union_candidates(trace, name)]


def _trace_union_candidates(
    trace: RetrievalTrace, name: RetrievalStageName
) -> list[RetrievalTraceCandidate]:
    candidates: list[RetrievalTraceCandidate] = []
    seen: set[tuple[object, ...]] = set()
    for stage in trace.stages:
        if stage.name != name:
            continue
        for candidate in stage.candidates:
            identity = _candidate_identity(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(candidate)
    return candidates


def _unique_trace_candidates(
    candidates: list[RetrievalTraceCandidate],
) -> list[RetrievalTraceCandidate]:
    unique: list[RetrievalTraceCandidate] = []
    seen: set[tuple[object, ...]] = set()
    for candidate in candidates:
        identity = _candidate_identity(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(candidate)
    return unique


def _candidate_identity(candidate: RetrievalTraceCandidate) -> tuple[object, ...]:
    return (
        candidate.doc_id,
        candidate.point_id,
        candidate.chunk_id,
        candidate.page,
        candidate.page_start,
        candidate.page_end,
    )


def _row_page(row: dict[str, Any]) -> int | None:
    for key in ("page", "page_start"):
        value = row.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _indexed_expected_docs(
    case: EvaluationCase,
    *,
    documents: list[DocumentRecord],
) -> tuple[list[str], list[str]]:
    if not case.expected_source_docs:
        return [], []
    titles = [str(document.title or "") for document in documents]
    normalized_titles = {_normalize_title(title): title for title in titles}
    found: list[str] = []
    missing: list[str] = []
    for expected in case.expected_source_docs:
        normalized = _normalize_title(expected)
        if normalized in normalized_titles:
            found.append(normalized_titles[normalized])
        else:
            missing.append(expected)
    return found, missing


def _current_complete_documents(
    document_repo: DocumentRepository,
) -> list[DocumentRecord]:
    return [
        document
        for document in document_repo.list_documents(state="active")
        if bool(getattr(document, "is_current", False))
        and getattr(document, "ingest_status", None) == "complete"
        and getattr(document, "deleted_at", None) is None
    ]


def _evidence_expectation_diagnostic(
    expectations: list[EvaluationEvidenceExpectation],
    *,
    trace: RetrievalTrace,
    documents: list[DocumentRecord],
) -> dict[str, Any]:
    resolved = [
        _resolve_evidence_expectation(index, expectation, documents=documents)
        for index, expectation in enumerate(expectations)
    ]
    stages: dict[str, dict[str, Any]] = {}
    for name in _EVIDENCE_STAGE_NAMES:
        candidates, stage_status = _evidence_stage_candidates(trace, name)
        stages[name] = _evidence_stage_diagnostic(
            resolved,
            candidates=candidates,
            attempts=[stage.attempt for stage in trace.stages if stage.name == name],
        )
        stages[name]["status"] = stage_status
    resolution_passed = all(item.document is not None for item in resolved)
    return {
        "required": bool(expectations),
        "passed": resolution_passed
        and all(stage["passed"] for stage in stages.values()),
        "resolution_passed": resolution_passed,
        "expectations": [_resolved_expectation_row(item) for item in resolved],
        "stages": stages,
    }


def _evidence_stage_candidates(
    trace: RetrievalTrace,
    name: RetrievalStageName,
) -> tuple[list[RetrievalTraceCandidate], str]:
    matching = [stage for stage in trace.stages if stage.name == name]
    if not matching:
        return [], "missing"
    if name != "rerank_input" or not any(
        stage.status == "skipped" for stage in matching
    ):
        return _trace_union_candidates(trace, name), "completed"

    skipped_attempts = {
        stage.attempt for stage in matching if stage.status == "skipped"
    }
    pass_through = RetrievalTrace(
        tuple(
            stage
            for stage in trace.stages
            if stage.name == "retrieved" and stage.attempt in skipped_attempts
        )
    )
    candidates = _unique_trace_candidates(
        [
            *_trace_union_candidates(trace, name),
            *_trace_union_candidates(pass_through, "retrieved"),
        ]
    )
    status = (
        "skipped"
        if matching and all(stage.status == "skipped" for stage in matching)
        else "partially_skipped"
    )
    return candidates, status


def _resolve_evidence_expectation(
    index: int,
    expectation: EvaluationEvidenceExpectation,
    *,
    documents: list[DocumentRecord],
) -> _ResolvedEvidenceExpectation:
    matches = documents
    if expectation.document_id:
        matches = [
            document
            for document in matches
            if getattr(document, "id", None) == expectation.document_id
        ]
    if expectation.content_hash:
        matches = [
            document
            for document in matches
            if getattr(document, "content_hash", None) == expectation.content_hash
        ]
    if len(matches) == 1:
        return _ResolvedEvidenceExpectation(
            index=index,
            expectation=expectation,
            document=matches[0],
            resolution_status="resolved",
        )
    return _ResolvedEvidenceExpectation(
        index=index,
        expectation=expectation,
        document=None,
        resolution_status="ambiguous" if len(matches) > 1 else "unresolved",
    )


def _resolved_expectation_row(
    resolved: _ResolvedEvidenceExpectation,
) -> dict[str, Any]:
    expectation = resolved.expectation
    row: dict[str, Any] = {
        "index": resolved.index,
        "document_id": expectation.document_id,
        "content_hash": expectation.content_hash,
        "pages": list(expectation.pages),
        "page_match": expectation.page_match,
        "required_anchor_count": len(expectation.anchors),
        "min_anchor_recall": expectation.min_anchor_recall,
        "resolution_status": resolved.resolution_status,
    }
    if resolved.document is not None:
        row.update(
            {
                "resolved_document_id": resolved.document.id,
                "resolved_document_title": resolved.document.title,
                "resolved_content_hash": resolved.document.content_hash,
            }
        )
    return row


def _evidence_stage_diagnostic(
    resolved: list[_ResolvedEvidenceExpectation],
    *,
    candidates: list[RetrievalTraceCandidate],
    attempts: list[int],
) -> dict[str, Any]:
    expectation_results: list[dict[str, Any]] = []
    for item in resolved:
        document_id = item.document.id if item.document is not None else None
        document_candidates = (
            [candidate for candidate in candidates if candidate.doc_id == document_id]
            if document_id
            else []
        )
        matched_pages = [
            page
            for page in item.expectation.pages
            if any(
                _candidate_covers_page(candidate, page)
                for candidate in document_candidates
            )
        ]
        anchor_candidates = [
            candidate
            for candidate in document_candidates
            if not item.expectation.pages
            or any(
                _candidate_covers_page(candidate, page)
                for page in item.expectation.pages
            )
        ]
        normalized_candidates = [
            _normalize_anchor_text(candidate.evidence_text)
            for candidate in anchor_candidates
            if candidate.evidence_text
        ]
        matched_anchor_indexes = [
            index
            for index, anchor in enumerate(item.expectation.anchors)
            if any(
                _contains_normalized_phrase(text, _normalize_anchor_text(anchor))
                for text in normalized_candidates
            )
        ]
        required_anchor_count = len(item.expectation.anchors)
        anchor_recall = (
            len(matched_anchor_indexes) / required_anchor_count
            if required_anchor_count
            else 1.0
        )
        anchors_passed = anchor_recall >= item.expectation.min_anchor_recall
        if item.document is None:
            pages_passed = False
        elif not item.expectation.pages:
            pages_passed = bool(document_candidates)
        elif item.expectation.page_match == "all":
            pages_passed = len(matched_pages) == len(item.expectation.pages)
        else:
            pages_passed = bool(matched_pages)
        passed = pages_passed and anchors_passed
        expectation_results.append(
            {
                "index": item.index,
                "resolved_document_id": document_id,
                "candidate_count": len(document_candidates),
                "matched_pages": matched_pages,
                "required_anchor_count": required_anchor_count,
                "matched_anchor_count": len(matched_anchor_indexes),
                "matched_anchor_indexes": matched_anchor_indexes,
                "anchor_recall": anchor_recall,
                "anchors_passed": anchors_passed,
                "passed": passed,
            }
        )
    return {
        "passed": all(item["passed"] for item in expectation_results),
        "candidate_count": len(candidates),
        "attempts": list(dict.fromkeys(attempts)),
        "expectations": expectation_results,
    }


def _candidate_covers_page(candidate: RetrievalTraceCandidate, page: int) -> bool:
    return _row_covers_page(candidate.to_row(), page)


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    if phrase.isascii():
        return f" {phrase} " in f" {text} "
    return phrase in text


def _normalize_anchor_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(_ANCHOR_TOKEN_RE.findall(normalized))


def _legacy_page_expectation_diagnostic(
    case: EvaluationCase,
    *,
    retrieved_rows: list[dict[str, Any]],
    documents: list[DocumentRecord],
) -> dict[str, Any]:
    expected_pages = list(dict.fromkeys(case.acceptable_source_pages))
    base: dict[str, Any] = {
        "required": bool(expected_pages),
        "deprecated": True,
        "expected_source_docs": list(case.expected_source_docs),
        "expected_pages": expected_pages,
        "matched_pages": [],
        "resolved_document_id": None,
        "resolution_status": "not_required",
        "ambiguous": False,
        "passed": True,
    }
    if not expected_pages:
        return base
    if len(case.expected_source_docs) != 1:
        base.update(
            {
                "resolution_status": (
                    "ambiguous" if case.expected_source_docs else "unresolved"
                ),
                "ambiguous": bool(case.expected_source_docs),
                "passed": False,
                "message": "Legacy page expectations require exactly one expected_source_doc.",
            }
        )
        return base
    expected_title = _normalize_title(case.expected_source_docs[0])
    matching_documents = [
        document
        for document in documents
        if _normalize_title(str(document.title or "")) == expected_title
    ]
    if len(matching_documents) != 1:
        base.update(
            {
                "resolution_status": (
                    "ambiguous" if len(matching_documents) > 1 else "unresolved"
                ),
                "ambiguous": len(matching_documents) > 1,
                "passed": False,
                "message": "Legacy expected_source_doc did not resolve to exactly one current complete document.",
            }
        )
        return base
    document = matching_documents[0]
    document_rows = [row for row in retrieved_rows if row.get("doc_id") == document.id]
    matched_pages = [
        page
        for page in expected_pages
        if any(_row_covers_page(row, page) for row in document_rows)
    ]
    base.update(
        {
            "resolution_status": "resolved",
            "resolved_document_id": document.id,
            "matched_pages": matched_pages,
            "passed": bool(matched_pages),
        }
    )
    return base


def _row_covers_page(row: dict[str, Any], page: int) -> bool:
    direct_page = row.get("page")
    if isinstance(direct_page, int) and not isinstance(direct_page, bool):
        if direct_page == page:
            return True
    start = row.get("page_start")
    end = row.get("page_end")
    valid_start = (
        start if isinstance(start, int) and not isinstance(start, bool) else None
    )
    valid_end = end if isinstance(end, int) and not isinstance(end, bool) else None
    if valid_start is None and valid_end is None:
        return False
    range_start = valid_start if valid_start is not None else valid_end
    range_end = valid_end if valid_end is not None else valid_start
    return bool(
        range_start is not None
        and range_end is not None
        and range_start <= page <= range_end
    )


def _expected_docs_retrieved(
    expected_docs: list[str], actual_titles: list[str]
) -> bool:
    if not expected_docs:
        return True
    actual = {_normalize_title(title) for title in actual_titles}
    return {_normalize_title(title) for title in expected_docs}.issubset(actual)


def _normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
