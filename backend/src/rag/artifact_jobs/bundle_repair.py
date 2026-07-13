"""Repair and normalization of evidence-backed artifact bundles."""

from __future__ import annotations

from collections.abc import Callable
import json

from .contracts import (
    ArtifactContentBundle,
    ContentBlock,
    ContentSection,
    EvidenceCitation,
    EvidenceManifest,
    PresentationSlide,
)
from .format_adaptation import (
    _is_generated_references_slide,
    _presentation_slides,
)
from .generation import ArtifactJsonGenerator
from .llm_json import generate_contract


def repair_document_bundle(
    bundle: ArtifactContentBundle,
    *,
    errors: list[str],
    evidence: EvidenceManifest,
    inference: ArtifactJsonGenerator,
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
        _repair_section(
            section,
            errors,
            f"content section {section.title}",
            empty_text=section.title,
        )
        for section in bundle.content.sections
    ]
    paginated_sections = [
        _repair_section(
            section,
            errors,
            f"paginated section {section.title}",
            empty_text=section.title,
        )
        for section in bundle.paginated.sections
    ]
    slides = []
    for index, slide in enumerate(bundle.presentation.slides, start=1):
        repaired = _repair_blocks(
            slide.blocks, errors, f"slide {index} ({slide.title})"
        )
        slides.append(
            slide.model_copy(
                update={
                    "blocks": repaired
                    or [ContentBlock(kind="heading", text=slide.title)]
                }
            )
        )
    repaired_bundle = bundle.model_copy(
        update={
            "content": bundle.content.model_copy(update={"sections": content_sections}),
            "paginated": bundle.paginated.model_copy(
                update={"sections": paginated_sections}
            ),
            "presentation": bundle.presentation.model_copy(update={"slides": slides}),
        }
    )
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
            table = block.table.model_copy(
                update={
                    "rows": [
                        row.model_copy(
                            update={"evidence_ids": normalize_ids(row.evidence_ids)}
                        )
                        for row in block.table.rows
                    ]
                }
            )
        return block.model_copy(
            update={
                "evidence_ids": normalize_ids(block.evidence_ids),
                "list_items": [
                    item.model_copy(
                        update={"evidence_ids": normalize_ids(item.evidence_ids)}
                    )
                    for item in block.list_items
                ],
                "entries": [
                    entry.model_copy(
                        update={"evidence_ids": normalize_ids(entry.evidence_ids)}
                    )
                    for entry in block.entries
                ],
                "table": table,
            }
        )

    def normalize_section(section: ContentSection) -> ContentSection:
        return section.model_copy(
            update={"blocks": [normalize_block(block) for block in section.blocks]}
        )

    content_sections = [
        normalize_section(section) for section in bundle.content.sections
    ]
    paginated_sections = [
        normalize_section(section) for section in bundle.paginated.sections
    ]
    slides = [
        slide.model_copy(
            update={"blocks": [normalize_block(block) for block in slide.blocks]}
        )
        for slide in bundle.presentation.slides
        if not _is_generated_references_slide(slide)
    ]
    if not slides:
        slides = _presentation_slides(content_sections)
    used_ids = _used_bundle_evidence_ids(content_sections, paginated_sections, slides)
    citation_ids = list(
        dict.fromkeys(
            [citation.evidence_id for citation in bundle.content.citations] + used_ids
        )
    )
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
    return bundle.model_copy(
        update={
            "content": bundle.content.model_copy(
                update={
                    "sections": content_sections,
                    "citations": citations,
                }
            ),
            "paginated": bundle.paginated.model_copy(
                update={"sections": paginated_sections}
            ),
            "presentation": bundle.presentation.model_copy(update={"slides": slides}),
        }
    )


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


def _collect_block_evidence_ids(
    block: ContentBlock, add: Callable[[list[str]], None]
) -> None:
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
    return section.model_copy(
        update={"blocks": blocks or [ContentBlock(kind="heading", text=empty_text)]}
    )


def _repair_blocks(
    blocks: list[ContentBlock], errors: list[str], location: str
) -> list[ContentBlock]:
    repaired = list(blocks)
    for index in range(len(blocks), 0, -1):
        label = f"{location} block {index}"
        block = repaired[index - 1]
        if any(
            error.startswith(label)
            and " list item " not in error
            and " key-value entry " not in error
            and " table row " not in error
            for error in errors
        ):
            repaired.pop(index - 1)
            continue
        if block.kind in {"bullet_list", "numbered_list"}:
            repaired[index - 1] = _repair_list_block(block, errors, label)
        elif block.kind == "key_value":
            repaired[index - 1] = _repair_key_value_block(block, errors, label)
        elif block.kind == "table" and block.table is not None:
            repaired[index - 1] = _repair_table_block(block, errors, label)
    return [block for block in repaired if _block_has_payload(block)]


def _repair_list_block(
    block: ContentBlock, errors: list[str], label: str
) -> ContentBlock:
    if block.list_items:
        items = [
            item
            for idx, item in enumerate(block.list_items, start=1)
            if not any(
                error.startswith(f"{label} list item {idx} ") for error in errors
            )
        ]
        return block.model_copy(update={"list_items": items})
    items = [
        item
        for idx, item in enumerate(block.items, start=1)
        if not any(error.startswith(f"{label} list item {idx} ") for error in errors)
    ]
    return block.model_copy(update={"items": items})


def _repair_key_value_block(
    block: ContentBlock, errors: list[str], label: str
) -> ContentBlock:
    entries = [
        entry
        for idx, entry in enumerate(block.entries, start=1)
        if not any(
            error.startswith(f"{label} key-value entry {idx} ") for error in errors
        )
    ]
    return block.model_copy(update={"entries": entries})


def _repair_table_block(
    block: ContentBlock, errors: list[str], label: str
) -> ContentBlock:
    rows = [
        row
        for idx, row in enumerate(block.table.rows, start=1)
        if not any(error.startswith(f"{label} table row {idx} ") for error in errors)
    ]
    return block.model_copy(
        update={"table": block.table.model_copy(update={"rows": rows})}
    )


def _block_has_payload(block: ContentBlock) -> bool:
    if block.kind in {"bullet_list", "numbered_list"}:
        return bool(block.list_items or block.items)
    if block.kind == "key_value":
        return bool(block.entries)
    if block.kind == "table":
        return bool(block.table and block.table.rows)
    return True
