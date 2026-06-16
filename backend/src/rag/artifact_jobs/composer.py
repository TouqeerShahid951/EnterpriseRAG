"""Evidence-linked LLM composition and format adaptation."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import json
import logging
import signal
import threading

from billiard.exceptions import SoftTimeLimitExceeded

from ..repositories.artifact_jobs import ArtifactJobRecord
from .contracts import (
    ArtifactContentBundle,
    ContentBlock,
    ContentListItem,
    ContentSection,
    ContentTable,
    ContentTableRow,
    DocumentPlan,
    EvidenceBackedContent,
    EvidenceCitation,
    EvidenceManifest,
    EvidenceRecord,
    FormatSpecifications,
    PaginatedDocumentSpec,
    PresentationSlide,
    PresentationSpec,
)
from .llm_json import generate_contract


COMPOSER_PROMPT_VERSION = "document-composer-v2.1"
FORMATTER_PROMPT_VERSION = "document-formatter-deterministic-v2.2"
MAX_RECORDS_PER_COMPOSITION_CALL = 40
COMPOSITION_RECORD_TEXT_LIMIT = 900
MAX_BLOCKS_PER_SLIDE = 4
MAX_PRESENTATION_SLIDES = 80
FALLBACK_MAX_LIST_ITEMS = 12

logger = logging.getLogger("rag.artifact_jobs")


def compose_document_bundle(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    evidence: EvidenceManifest,
    *,
    inference: object,
    model: str | None,
    section_timeout_seconds: float | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> ArtifactContentBundle:
    sections: list[ContentSection] = []
    section_batches = []
    for planned, evidence_section in zip(plan.sections, evidence.sections, strict=True):
        records = evidence_section.records
        if not records:
            continue
        batches = [
            records[offset : offset + MAX_RECORDS_PER_COMPOSITION_CALL]
            for offset in range(0, len(records), MAX_RECORDS_PER_COMPOSITION_CALL)
        ]
        section_batches.append((planned, batches))

    completed_batches = 0
    total_batches = sum(len(batches) for _, batches in section_batches)
    for planned, batches in section_batches:
        batch_sections: list[ContentSection] = []
        for batch in batches:
            if progress_callback:
                progress_callback(completed_batches + 1, total_batches, "batch")
            batch_sections.append(
                _compose_section_with_fallback(
                    job,
                    plan,
                    planned.title,
                    planned.objective,
                    planned.preferred_blocks,
                    batch,
                    inference=inference,
                    model=model,
                    section_timeout_seconds=section_timeout_seconds,
                )
            )
            completed_batches += 1
            if progress_callback:
                progress_callback(completed_batches, total_batches, "batch_complete")
        sections.append(
            ContentSection(
                title=planned.title,
                blocks=[block for batch_section in batch_sections for block in batch_section.blocks],
            )
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
        for record in _dedupe_records(evidence.records)
    ]
    warnings = [
        warning
        for section in evidence.sections
        for warning in section.warnings
    ]
    if progress_callback:
        progress_callback(total_batches, max(total_batches, 1), "formatting")
    content = EvidenceBackedContent(
        title=plan.title,
        purpose=plan.purpose,
        sections=sections,
        citations=citations,
        warnings=list(dict.fromkeys(warnings)),
    )
    formats = _adapt_formats(job, plan, content)
    return ArtifactContentBundle(
        content=content,
        paginated=formats.paginated,
        presentation=formats.presentation,
    )


def repair_document_bundle(
    bundle: ArtifactContentBundle,
    *,
    errors: list[str],
    evidence: EvidenceManifest,
    inference: object,
    model: str | None,
) -> ArtifactContentBundle:
    allowed = [record.evidence_id for record in evidence.records]
    prompt = (
        "Repair this document bundle using only the allowed evidence IDs. Preserve supported content, "
        "remove or rewrite unsupported factual statements, and ensure every factual paragraph, list item, "
        "quotation, callout, key-value entry, table row, and slide claim has valid evidence IDs. "
        "Return only JSON matching the schema.\n\n"
        f"Validation errors:\n{json.dumps(errors)}\n\n"
        f"Allowed evidence IDs:\n{json.dumps(allowed)}\n\n"
        f"Bundle:\n{bundle.model_dump_json()}\n\n"
        f"Schema:\n{json.dumps(ArtifactContentBundle.model_json_schema(), separators=(',', ':'))}"
    )
    return generate_contract(
        inference=inference,
        model=model,
        system="You repair evidence-backed enterprise document specifications.",
        prompt=prompt,
        contract=ArtifactContentBundle,
    )


def _compose_section(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    title: str,
    objective: str,
    preferred_blocks: list[str],
    records: list[EvidenceRecord],
    *,
    inference: object,
    model: str | None,
) -> ContentSection:
    evidence_payload = [
        {
            "evidence_id": record.evidence_id,
            "document": record.doc_title,
            "page_start": record.page_start,
            "page_end": record.page_end,
            "content_type": record.content_type,
            "text": record.text[:COMPOSITION_RECORD_TEXT_LIMIT],
            "structured_fields": record.structured_fields,
        }
        for record in records
    ]
    prompt = (
        "Compose one semantic document section using only the supplied evidence. The section structure "
        "must follow the request, not a fixed template. Every factual paragraph, quotation, callout, list "
        "item, key-value entry, and table row must cite one or more exact evidence_id values. Use list_items "
        "with per-item evidence_ids for bullet_list and numbered_list blocks. Headings and "
        "break blocks do not require evidence IDs. Preserve exhaustive structured rows in tables or lists. "
        "Do not mention the prompt, retrieval, or generation process. Return only JSON matching the schema.\n\n"
        f"Original request:\n{job.original_request}\n\n"
        f"Document purpose: {plan.purpose}\nAudience: {plan.audience}\nTone: {plan.tone}\n"
        f"Section title: {title}\nSection objective: {objective}\n"
        f"Preferred blocks: {json.dumps(preferred_blocks)}\n\n"
        f"Evidence:\n{json.dumps(evidence_payload, ensure_ascii=True)}\n\n"
        f"Schema:\n{json.dumps(ContentSection.model_json_schema(), separators=(',', ':'))}"
    )
    section = generate_contract(
        inference=inference,
        model=model,
        system="You compose precise, citation-preserving enterprise document sections.",
        prompt=prompt,
        contract=ContentSection,
    )
    return section.model_copy(update={"title": title})


def _compose_section_with_fallback(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    title: str,
    objective: str,
    preferred_blocks: list[str],
    records: list[EvidenceRecord],
    *,
    inference: object,
    model: str | None,
    section_timeout_seconds: float | None,
) -> ContentSection:
    try:
        with _section_deadline(section_timeout_seconds):
            return _compose_section(
                job,
                plan,
                title,
                objective,
                preferred_blocks,
                records,
                inference=inference,
                model=model,
            )
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning(
            "artifact section composition fallback job_id=%s section_title=%s error_type=%s",
            job.id,
            title,
            type(exc).__name__,
        )
        return _fallback_section(title, records)


@contextmanager
def _section_deadline(seconds: float | None):
    if not seconds or threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def raise_timeout(_signum, _frame) -> None:
        raise TimeoutError("artifact section composition timed out")

    signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _fallback_section(title: str, records: list[EvidenceRecord]) -> ContentSection:
    structured_records = [record for record in records if record.structured_fields]
    if structured_records:
        headers = _fallback_headers(structured_records)
        rows = [
            ContentTableRow(
                values=[record.structured_fields.get(header, "") for header in headers],
                evidence_ids=[record.evidence_id],
            )
            for record in structured_records
        ]
        return ContentSection(
            title=title,
            blocks=[ContentBlock(kind="table", table=ContentTable(headers=headers, rows=rows))],
        )
    return ContentSection(
        title=title,
        blocks=[
            ContentBlock(
                kind="bullet_list",
                list_items=[
                    ContentListItem(text=_fallback_item_text(record), evidence_ids=[record.evidence_id])
                    for record in records[:FALLBACK_MAX_LIST_ITEMS]
                ],
            )
        ],
    )


def _fallback_headers(records: list[EvidenceRecord]) -> list[str]:
    headers: list[str] = []
    for record in records:
        for key in record.structured_fields:
            if key not in headers:
                headers.append(key)
    return headers or ["Evidence"]


def _fallback_item_text(record: EvidenceRecord) -> str:
    text = " ".join((record.text or "").split())
    if not text and record.structured_fields:
        text = "; ".join(f"{key}: {value}" for key, value in record.structured_fields.items())
    return text[:360] or f"Evidence item {record.evidence_id}"


def _adapt_formats(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    content: EvidenceBackedContent,
) -> FormatSpecifications:
    subtitle = _subtitle(plan)
    return FormatSpecifications(
        paginated=PaginatedDocumentSpec(
            title=content.title,
            subtitle=subtitle,
            sections=content.sections,
            include_references=True,
            include_coverage_notes=True,
        ),
        presentation=PresentationSpec(
            title=content.title,
            subtitle=subtitle,
            slides=_presentation_slides(content.sections),
            include_references_slide=True,
        ),
    )


def _dedupe_records(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    seen: set[str] = set()
    result: list[EvidenceRecord] = []
    for record in records:
        if record.evidence_id in seen:
            continue
        seen.add(record.evidence_id)
        result.append(record)
    return result


def _subtitle(plan: DocumentPlan) -> str:
    return f"{plan.document_type.title()} for {plan.audience}"


def _presentation_slides(sections: list[ContentSection]) -> list[PresentationSlide]:
    slides: list[PresentationSlide] = []
    for section in sections:
        for index, blocks in enumerate(_chunks(section.blocks, MAX_BLOCKS_PER_SLIDE), start=1):
            title = section.title if index == 1 else f"{section.title} ({index})"
            slides.append(PresentationSlide(title=title, blocks=blocks))
            if len(slides) >= MAX_PRESENTATION_SLIDES:
                return slides
    return slides


def _chunks(blocks: list, size: int) -> list[list]:
    return [blocks[offset : offset + size] for offset in range(0, len(blocks), size)]
