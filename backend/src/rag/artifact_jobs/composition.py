"""Primary evidence-linked artifact composition orchestration."""

from __future__ import annotations

from collections.abc import Callable
import json
import logging

from billiard.exceptions import SoftTimeLimitExceeded

from .bundle_repair import normalize_bundle_evidence_ids
from .composition_deadline import _section_deadline
from .contracts import (
    ArtifactContentBundle,
    ContentSection,
    DocumentPlan,
    EvidenceBackedContent,
    EvidenceCitation,
    EvidenceManifest,
    EvidenceRecord,
)
from .fallback_composition import _fallback_section
from .format_adaptation import _adapt_formats
from .generation import ArtifactGenerationError, ArtifactJsonGenerator
from .job_models import ArtifactJobRecord
from .llm_json import LlmContractError, generate_contract


COMPOSER_PROMPT_VERSION = "document-composer-v2.1"
MAX_RECORDS_PER_COMPOSITION_CALL = 40
COMPOSITION_RECORD_TEXT_LIMIT = 900

logger = logging.getLogger("rag.artifact_jobs")


def compose_document_bundle(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    evidence: EvidenceManifest,
    *,
    inference: ArtifactJsonGenerator,
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
                blocks=[
                    block
                    for batch_section in batch_sections
                    for block in batch_section.blocks
                ],
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
        warning for section in evidence.sections for warning in section.warnings
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
    formats = _adapt_formats(
        job,
        plan,
        content,
        inference=inference,
        model=model,
        timeout_seconds=section_timeout_seconds,
    )
    return normalize_bundle_evidence_ids(
        ArtifactContentBundle(
            content=content,
            paginated=formats.paginated,
            presentation=formats.presentation,
        ),
        evidence,
    )


def _compose_section(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    title: str,
    objective: str,
    preferred_blocks: list[str],
    records: list[EvidenceRecord],
    *,
    inference: ArtifactJsonGenerator,
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
    inference: ArtifactJsonGenerator,
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
    except (ArtifactGenerationError, LlmContractError, TimeoutError) as exc:
        logger.warning(
            "artifact section composition fallback job_id=%s section_title=%s error_type=%s",
            job.id,
            title,
            type(exc).__name__,
        )
        return _fallback_section(title, records)


def _dedupe_records(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    seen: set[str] = set()
    result: list[EvidenceRecord] = []
    for record in records:
        if record.evidence_id in seen:
            continue
        seen.add(record.evidence_id)
        result.append(record)
    return result
