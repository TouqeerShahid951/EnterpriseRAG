"""Build render-ready artifact contracts from one grounded RAG answer."""

from __future__ import annotations

from hashlib import sha256
import re

from rag.shared.contracts.evidence import SourceAnchor

from .contracts import (
    ArtifactContentBundle,
    ContentBlock,
    ContentSection,
    DocumentPlan,
    DocumentPlanSection,
    EvidenceBackedContent,
    EvidenceCitation,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceSection,
    PaginatedDocumentSpec,
    PresentationSpec,
)
from .generation.format_adaptation import _presentation_slides


def grounded_response_is_ready(
    *,
    sources: list[SourceAnchor],
    degraded: bool,
    faithfulness_status: object,
) -> bool:
    return (
        bool(sources)
        and not degraded
        and faithfulness_status == "checked"
    )


def build_grounded_artifact_payload(
    *,
    original_request: str,
    content_query: str,
    answer: str,
    sources: list[SourceAnchor],
) -> tuple[DocumentPlan, EvidenceManifest, ArtifactContentBundle]:
    records = [
        _record_from_source(source, content_query=content_query)
        for source in _dedupe_sources(sources)
    ]
    evidence_ids = [record.evidence_id for record in records]
    title = _title_from_query(content_query)
    section = ContentSection(
        title="Grounded answer",
        blocks=[
            ContentBlock(
                kind="paragraph",
                text=paragraph,
                evidence_ids=evidence_ids,
            )
            for paragraph in _answer_paragraphs(answer)
        ],
    )
    plan = DocumentPlan(
        title=title,
        purpose=f"Render the grounded answer for: {original_request}",
        assumptions=[
            "The content came from the previously displayed grounded answer.",
            "References are the source anchors selected for that answer.",
        ],
        sections=[
            DocumentPlanSection(
                title=section.title,
                objective=f"Format the grounded answer for: {content_query}",
                preferred_blocks=["paragraph"],
                retrieval_queries=[content_query],
                coverage_requirement="grounded_rag_response",
            )
        ],
    )
    evidence = EvidenceManifest(
        sections=[
            EvidenceSection(
                title=section.title,
                objective=f"Evidence selected for: {content_query}",
                retrieval_mode="focused_search",
                coverage_requirement="grounded_rag_response",
                coverage_status="sufficient",
                records=records,
                warnings=["Rendered from the previously displayed grounded answer."],
                searched_query_count=1,
                top_k_record_count=len(records),
            )
        ]
    )
    citations = [
        EvidenceCitation(
            evidence_id=record.evidence_id,
            doc_id=record.doc_id,
            doc_title=record.doc_title,
            chunk_id=record.chunk_id,
            page_start=record.page_start,
            page_end=record.page_end,
        )
        for record in records
    ]
    content = EvidenceBackedContent(
        title=title,
        purpose=plan.purpose,
        sections=[section],
        citations=citations,
        warnings=["Rendered from the previously displayed grounded answer."],
    )
    return plan, evidence, ArtifactContentBundle(
        content=content,
        paginated=PaginatedDocumentSpec(
            title=title,
            subtitle="Grounded RAG response",
            sections=[section],
        ),
        presentation=PresentationSpec(
            title=title,
            subtitle="Grounded RAG response",
            slides=_presentation_slides([section]),
        ),
    )


def _record_from_source(
    source: SourceAnchor,
    *,
    content_query: str,
) -> EvidenceRecord:
    page_start = source.page_start if source.page_start is not None else source.page
    page_end = source.page_end if source.page_end is not None else page_start
    return EvidenceRecord(
        evidence_id="ev_"
        + sha256(f"{source.doc_id}:{source.chunk_id}".encode()).hexdigest()[:20],
        section_title="Grounded answer",
        query=content_query,
        doc_id=source.doc_id,
        doc_title=source.doc_title,
        chunk_id=source.chunk_id,
        page_start=page_start,
        page_end=page_end,
        content_type="source_anchor",
        text=source.excerpt,
    )


def _dedupe_sources(sources: list[SourceAnchor]) -> list[SourceAnchor]:
    seen: set[tuple[str, str]] = set()
    result: list[SourceAnchor] = []
    for source in sources:
        key = (source.doc_id, source.chunk_id)
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


def _answer_paragraphs(answer: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n{2,}", answer) if part.strip()]


def _title_from_query(query: str) -> str:
    words = query.strip(" .").split()
    title = " ".join(
        word.upper() if word.isupper() else word.capitalize() for word in words[:12]
    )
    return title[:180] or "Generated Document"
