"""Evidence-linked LLM composition and format adaptation."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import json
import logging
import re
import signal
import threading

from billiard.exceptions import SoftTimeLimitExceeded

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
from .job_models import ArtifactJobRecord
from .llm_json import generate_contract


COMPOSER_PROMPT_VERSION = "document-composer-v2.1"
FORMATTER_PROMPT_VERSION = "document-formatter-llm-v3.0"
MAX_RECORDS_PER_COMPOSITION_CALL = 40
COMPOSITION_RECORD_TEXT_LIMIT = 900
MAX_BLOCKS_PER_SLIDE = 4
MAX_PRESENTATION_SLIDES = 80
FALLBACK_MAX_LIST_ITEMS = 12
FALLBACK_MAX_TABLE_COLUMNS = 6
REFERENCE_SLIDE_TITLES = {"reference", "references", "source", "sources", "citation", "citations", "bibliography"}

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
    formats = _adapt_formats(
        job,
        plan,
        content,
        inference=inference,
        model=model,
        timeout_seconds=section_timeout_seconds,
    )
    return normalize_bundle_evidence_ids(ArtifactContentBundle(
        content=content,
        paginated=formats.paginated,
        presentation=formats.presentation,
    ), evidence)


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


def fallback_repair_document_bundle(
    bundle: ArtifactContentBundle,
    *,
    errors: list[str],
    evidence: EvidenceManifest,
) -> ArtifactContentBundle:
    content_sections = [
        _repair_section(section, errors, f"content section {section.title}", empty_text=section.title)
        for section in bundle.content.sections
    ]
    paginated_sections = [
        _repair_section(section, errors, f"paginated section {section.title}", empty_text=section.title)
        for section in bundle.paginated.sections
    ]
    slides = []
    for index, slide in enumerate(bundle.presentation.slides, start=1):
        repaired = _repair_blocks(slide.blocks, errors, f"slide {index} ({slide.title})")
        slides.append(slide.model_copy(update={"blocks": repaired or [ContentBlock(kind="heading", text=slide.title)]}))
    repaired_bundle = bundle.model_copy(update={
        "content": bundle.content.model_copy(update={"sections": content_sections}),
        "paginated": bundle.paginated.model_copy(update={"sections": paginated_sections}),
        "presentation": bundle.presentation.model_copy(update={"slides": slides}),
    })
    return normalize_bundle_evidence_ids(repaired_bundle, evidence)


def normalize_bundle_evidence_ids(
    bundle: ArtifactContentBundle,
    evidence: EvidenceManifest,
) -> ArtifactContentBundle:
    """Map recoverable evidence-id variants back to manifest IDs and refresh citations."""
    records_by_id = {record.evidence_id: record for record in evidence.records}
    aliases: dict[str, str] = {}
    for evidence_id in records_by_id:
        aliases[evidence_id] = evidence_id
        if evidence_id.startswith("ev_"):
            aliases[evidence_id.removeprefix("ev_")] = evidence_id
        else:
            aliases[f"ev_{evidence_id}"] = evidence_id

    def normalize_ids(evidence_ids: list[str]) -> list[str]:
        normalized: list[str] = []
        for evidence_id in evidence_ids:
            mapped = aliases.get(evidence_id)
            if mapped and mapped not in normalized:
                normalized.append(mapped)
        return normalized

    def normalize_block(block: ContentBlock) -> ContentBlock:
        table = None
        if block.table is not None:
            table = block.table.model_copy(update={
                "rows": [
                    row.model_copy(update={"evidence_ids": normalize_ids(row.evidence_ids)})
                    for row in block.table.rows
                ]
            })
        return block.model_copy(update={
            "evidence_ids": normalize_ids(block.evidence_ids),
            "list_items": [
                item.model_copy(update={"evidence_ids": normalize_ids(item.evidence_ids)})
                for item in block.list_items
            ],
            "entries": [
                entry.model_copy(update={"evidence_ids": normalize_ids(entry.evidence_ids)})
                for entry in block.entries
            ],
            "table": table,
        })

    def normalize_section(section: ContentSection) -> ContentSection:
        return section.model_copy(update={"blocks": [normalize_block(block) for block in section.blocks]})

    content_sections = [normalize_section(section) for section in bundle.content.sections]
    paginated_sections = [normalize_section(section) for section in bundle.paginated.sections]
    slides = [
        slide.model_copy(update={"blocks": [normalize_block(block) for block in slide.blocks]})
        for slide in bundle.presentation.slides
        if not _is_generated_references_slide(slide)
    ]
    if not slides:
        slides = _presentation_slides(content_sections)
    used_ids = _used_bundle_evidence_ids(content_sections, paginated_sections, slides)
    citation_ids = list(dict.fromkeys([citation.evidence_id for citation in bundle.content.citations] + used_ids))
    citations = [
        EvidenceCitation(
            evidence_id=evidence_id,
            doc_id=records_by_id[evidence_id].doc_id,
            doc_title=records_by_id[evidence_id].doc_title,
            chunk_id=records_by_id[evidence_id].chunk_id,
            page_start=records_by_id[evidence_id].page_start,
            page_end=records_by_id[evidence_id].page_end,
        )
        for evidence_id in citation_ids
        if evidence_id in records_by_id
    ]
    return bundle.model_copy(update={
        "content": bundle.content.model_copy(update={
            "sections": content_sections,
            "citations": citations,
        }),
        "paginated": bundle.paginated.model_copy(update={"sections": paginated_sections}),
        "presentation": bundle.presentation.model_copy(update={"slides": slides}),
    })


def _used_bundle_evidence_ids(
    content_sections: list[ContentSection],
    paginated_sections: list[ContentSection],
    slides: list[PresentationSlide],
) -> list[str]:
    used: list[str] = []

    def add(evidence_ids: list[str]) -> None:
        for evidence_id in evidence_ids:
            if evidence_id and evidence_id not in used:
                used.append(evidence_id)

    for section in [*content_sections, *paginated_sections]:
        for block in section.blocks:
            _collect_block_evidence_ids(block, add)
    for slide in slides:
        for block in slide.blocks:
            _collect_block_evidence_ids(block, add)
    return used


def _collect_block_evidence_ids(block: ContentBlock, add: Callable[[list[str]], None]) -> None:
    add(block.evidence_ids)
    for item in block.list_items:
        add(item.evidence_ids)
    for entry in block.entries:
        add(entry.evidence_ids)
    if block.table is not None:
        for row in block.table.rows:
            add(row.evidence_ids)


def _repair_section(
    section: ContentSection,
    errors: list[str],
    location: str,
    *,
    empty_text: str,
) -> ContentSection:
    blocks = _repair_blocks(section.blocks, errors, location)
    return section.model_copy(update={"blocks": blocks or [ContentBlock(kind="heading", text=empty_text)]})


def _repair_blocks(blocks: list[ContentBlock], errors: list[str], location: str) -> list[ContentBlock]:
    repaired = list(blocks)
    for index in range(len(blocks), 0, -1):
        label = f"{location} block {index}"
        block = repaired[index - 1]
        if any(error.startswith(label) and " list item " not in error and " key-value entry " not in error and " table row " not in error for error in errors):
            repaired.pop(index - 1)
            continue
        if block.kind in {"bullet_list", "numbered_list"}:
            repaired[index - 1] = _repair_list_block(block, errors, label)
        elif block.kind == "key_value":
            repaired[index - 1] = _repair_key_value_block(block, errors, label)
        elif block.kind == "table" and block.table is not None:
            repaired[index - 1] = _repair_table_block(block, errors, label)
    return [block for block in repaired if _block_has_payload(block)]


def _repair_list_block(block: ContentBlock, errors: list[str], label: str) -> ContentBlock:
    if block.list_items:
        items = [item for idx, item in enumerate(block.list_items, start=1) if not any(error.startswith(f"{label} list item {idx} ") for error in errors)]
        return block.model_copy(update={"list_items": items})
    items = [item for idx, item in enumerate(block.items, start=1) if not any(error.startswith(f"{label} list item {idx} ") for error in errors)]
    return block.model_copy(update={"items": items})


def _repair_key_value_block(block: ContentBlock, errors: list[str], label: str) -> ContentBlock:
    entries = [entry for idx, entry in enumerate(block.entries, start=1) if not any(error.startswith(f"{label} key-value entry {idx} ") for error in errors)]
    return block.model_copy(update={"entries": entries})


def _repair_table_block(block: ContentBlock, errors: list[str], label: str) -> ContentBlock:
    rows = [row for idx, row in enumerate(block.table.rows, start=1) if not any(error.startswith(f"{label} table row {idx} ") for error in errors)]
    return block.model_copy(update={"table": block.table.model_copy(update={"rows": rows})})


def _block_has_payload(block: ContentBlock) -> bool:
    if block.kind in {"bullet_list", "numbered_list"}:
        return bool(block.list_items or block.items)
    if block.kind == "key_value":
        return bool(block.entries)
    if block.kind == "table":
        return bool(block.table and block.table.rows)
    return True


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
    if _should_use_compact_record_table(records):
        return _fallback_compact_record_table(title, records)
    structured_records = [record for record in records if record.structured_fields]
    if structured_records:
        headers = _fallback_headers(structured_records)
        if len(headers) > FALLBACK_MAX_TABLE_COLUMNS:
            return _fallback_bullet_section(title, records)
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
    return _fallback_bullet_section(title, records)


def _fallback_bullet_section(title: str, records: list[EvidenceRecord]) -> ContentSection:
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


def _should_use_compact_record_table(records: list[EvidenceRecord]) -> bool:
    structured_records = [record for record in records if record.structured_fields]
    if not structured_records:
        return False
    unique_docs = {record.doc_title for record in records}
    return len(_fallback_headers(structured_records)) > FALLBACK_MAX_TABLE_COLUMNS or len(unique_docs) > 1


def _fallback_compact_record_table(title: str, records: list[EvidenceRecord]) -> ContentSection:
    grouped: dict[str, list[EvidenceRecord]] = {}
    for record in records:
        grouped.setdefault(record.doc_title, []).append(record)
    rows = [
        ContentTableRow(
            values=[
                doc_title,
                _topic_value(doc_title, doc_records),
                _key_detail_summary(doc_records),
                _evidence_or_status_summary(doc_records),
            ],
            evidence_ids=_record_ids(doc_records),
        )
        for doc_title, doc_records in sorted(grouped.items())
    ]
    if not rows:
        return _fallback_bullet_section(title, records)
    return ContentSection(
        title=title,
        blocks=[
            ContentBlock(
                kind="table",
                table=ContentTable(
                    headers=["Document", _fallback_topic_header(records), "Key details", "Evidence / status"],
                    rows=rows,
                ),
            )
        ],
    )


def _fallback_topic_header(records: list[EvidenceRecord]) -> str:
    text = " ".join(record.query for record in records).lower()
    rules = (
        (("crime", "criminal", "offence", "offense"), "Crime / offense"),
        (("risk", "issue"), "Risk / issue"),
        (("requirement", "shall", "must"), "Requirement"),
        (("control", "compliance"), "Control / compliance"),
        (("standard", "specification"), "Standard / specification"),
        (("event", "timeline", "date"), "Event"),
        (("finding", "observation"), "Finding"),
    )
    for needles, label in rules:
        if any(needle in text for needle in needles):
            return label
    return "Topic"


def _topic_value(doc_title: str, records: list[EvidenceRecord]) -> str:
    field_value = _first_field_value(records, (
        "subject",
        "title",
        "category",
        "classification",
        "type",
        "topic",
        "offense",
        "offence",
        "crime",
        "risk",
        "requirement",
        "standard",
        "control",
        "finding",
        "issue",
    ))
    if field_value:
        return _clip(field_value, 130)
    subject = _subject_from_title(doc_title)
    if subject.lower() not in {"document", "report", "fictitious", "untitled"}:
        return subject
    sentence = _first_matching_sentence(_records_text(records), ("registered", "section", "finding", "requirement", "risk", "status"))
    return _clip(sentence or subject, 130)


def _key_detail_summary(records: list[EvidenceRecord]) -> str:
    text = _field_summary(records, (
        "summary",
        "description",
        "detail",
        "legal",
        "requirement",
        "scope",
        "objective",
        "finding",
        "issue",
        "risk",
        "standard",
        "control",
        "date",
        "status",
    ))
    return _clip(text or _records_text(records), 260)


def _evidence_or_status_summary(records: list[EvidenceRecord]) -> str:
    text = _field_summary(records, (
        "evidence",
        "status",
        "action",
        "outcome",
        "result",
        "analysis",
        "finding",
        "note",
    ))
    if not text:
        text = _first_matching_sentence(_records_text(records), ("evidence", "status", "action", "result", "analysis", "finding"))
    return _clip(text or _records_text(records), 260)


def _first_field_value(records: list[EvidenceRecord], labels: tuple[str, ...]) -> str:
    for record in records:
        for key, value in record.structured_fields.items():
            if _is_useful_field(key) and any(label in key.lower() for label in labels):
                return value
    return ""


def _field_summary(records: list[EvidenceRecord], labels: tuple[str, ...], *, max_fields: int = 2) -> str:
    parts: list[str] = []
    for record in records:
        for key, value in record.structured_fields.items():
            if not _is_useful_field(key) or not any(label in key.lower() for label in labels):
                continue
            parts.append(f"{key}: {value}")
            if len(parts) >= max_fields:
                return " ".join(parts)
    return " ".join(parts)


def _is_useful_field(label: str) -> bool:
    lowered = label.lower()
    low_value = ("contact", "phone", "address", "signature", "cnic", "imei")
    return not any(term in lowered for term in low_value)


def _subject_from_title(doc_title: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", doc_title.rsplit("/", 1)[-1])
    words = [word for word in re.split(r"[^A-Za-z0-9]+", stem) if word and not word.isdigit()]
    if len(words) > 1 and words[0].isupper() and len(words[0]) <= 6:
        words = words[1:]
    subject = " ".join(words[:5]) or "Document"
    return " ".join(word.upper() if word.isupper() else word.capitalize() for word in subject.split())


def _records_text(records: list[EvidenceRecord]) -> str:
    parts: list[str] = []
    for record in records:
        parts.extend(record.structured_fields.values())
        parts.append(record.text)
    return " ".join(" ".join(part.split()) for part in parts if part)


def _first_matching_sentence(text: str, needles: tuple[str, ...]) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        lowered = sentence.lower()
        if any(needle in lowered for needle in needles):
            return sentence.strip()
    return ""


def _record_ids(records: list[EvidenceRecord]) -> list[str]:
    return list(dict.fromkeys(record.evidence_id for record in records))[:8]


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    return compact[: limit - 1].rstrip() + "..." if len(compact) > limit else compact


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
    *,
    inference: object,
    model: str | None,
    timeout_seconds: float | None,
) -> FormatSpecifications:
    try:
        with _section_deadline(timeout_seconds):
            return _adapt_formats_with_llm(job, plan, content, inference=inference, model=model)
    except Exception as exc:
        logger.warning(
            "artifact format adaptation fallback job_id=%s error_type=%s",
            job.id,
            type(exc).__name__,
        )
        return _adapt_formats_deterministic(plan, content)


def _adapt_formats_with_llm(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    content: EvidenceBackedContent,
    *,
    inference: object,
    model: str | None,
) -> FormatSpecifications:
    prompt = (
        "Create final DOCX/PDF and presentation formatting specifications from the composed evidence-backed content. "
        "You decide the artifact title, subtitle, number of presentation slides, slide titles, and which content blocks "
        "belong on each slide. You may choose paragraphs, bullets, key-value blocks, or tables when the existing content "
        "supports them. Preserve citations and use only the existing evidence IDs. Do not invent facts. Keep slides "
        "usable: prefer 1-3 blocks per slide, concise titles, and split dense content across multiple slides. The renderer "
        "may still add continuation slides if physical layout requires it. Do not include a slide titled References, "
        "Sources, Citations, or Bibliography; the renderer appends that slide from citations. Return only JSON matching "
        "the schema.\n\n"
        f"Original request:\n{job.original_request}\n\n"
        f"Plan:\n{plan.model_dump_json()}\n\n"
        f"Composed content:\n{content.model_dump_json()}\n\n"
        f"Schema:\n{json.dumps(FormatSpecifications.model_json_schema(), separators=(',', ':'))}"
    )
    formats = generate_contract(
        inference=inference,
        model=model,
        system="You are a presentation and document formatter for evidence-backed enterprise artifacts.",
        prompt=prompt,
        contract=FormatSpecifications,
    )
    return _normalized_formats(formats, content)


def _normalized_formats(formats: FormatSpecifications, content: EvidenceBackedContent) -> FormatSpecifications:
    paginated = formats.paginated.model_copy(update={
        "title": formats.paginated.title or content.title,
        "sections": formats.paginated.sections or content.sections,
        "include_references": True,
        "include_coverage_notes": True,
    })
    slides = _without_generated_references_slides(formats.presentation.slides or _presentation_slides(content.sections))
    if not slides:
        slides = _presentation_slides(content.sections)
    presentation = formats.presentation.model_copy(update={
        "title": formats.presentation.title or content.title,
        "slides": slides[:MAX_PRESENTATION_SLIDES],
        "include_references_slide": True,
    })
    return FormatSpecifications(paginated=paginated, presentation=presentation)


def _adapt_formats_deterministic(
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


def _without_generated_references_slides(slides: list[PresentationSlide]) -> list[PresentationSlide]:
    return [slide for slide in slides if not _is_generated_references_slide(slide)]


def _is_generated_references_slide(slide: PresentationSlide) -> bool:
    return _normalized_reference_title(slide.title) in REFERENCE_SLIDE_TITLES


def _normalized_reference_title(value: str) -> str:
    return re.sub(r"[^a-z]+", " ", value.lower()).strip()


def _chunks(blocks: list, size: int) -> list[list]:
    return [blocks[offset : offset + size] for offset in range(0, len(blocks), size)]
