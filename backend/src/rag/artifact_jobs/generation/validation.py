"""Deterministic validation for evidence-backed document specifications."""

from __future__ import annotations

import re

from rag.artifact_jobs.contracts import (
    ArtifactContentBundle,
    ArtifactContentValidation,
    ContentBlock,
    DocumentPlan,
    EvidenceManifest,
)


_FACTUAL_BLOCKS = {"paragraph", "quotation", "callout"}
_LIST_BLOCKS = {"bullet_list", "numbered_list"}
_STOPWORDS = {
    "about", "after", "also", "and", "are", "been", "being", "for", "from", "have",
    "into", "its", "that", "the", "their", "this", "was", "were", "with",
}


def validate_document_bundle(
    bundle: ArtifactContentBundle,
    *,
    plan: DocumentPlan,
    evidence: EvidenceManifest,
) -> ArtifactContentValidation:
    errors: list[str] = []
    warnings: list[str] = []
    evidence_by_id = {record.evidence_id: record for record in evidence.records}
    cited_ids = {citation.evidence_id for citation in bundle.content.citations}
    unknown_citations = cited_ids - set(evidence_by_id)
    if unknown_citations:
        errors.append(f"Unknown citations: {', '.join(sorted(unknown_citations)[:10])}")
    uncited_used_ids = _used_evidence_ids(bundle) - cited_ids
    if uncited_used_ids:
        errors.append(f"Evidence IDs used without citations: {', '.join(sorted(uncited_used_ids)[:10])}")
    planned_titles = {section.title for section in plan.sections}
    composed_titles = {section.title for section in bundle.content.sections}
    missing_sections = planned_titles - composed_titles
    if missing_sections:
        errors.append(f"Missing planned sections: {', '.join(sorted(missing_sections))}")

    supported = 0
    total = 0
    for location, block in _all_blocks(bundle):
        block_errors, block_supported, block_total = _validate_block(
            block,
            location=location,
            evidence_by_id=evidence_by_id,
        )
        errors.extend(block_errors)
        supported += block_supported
        total += block_total

    for section in evidence.sections:
        if section.coverage_status in {"none", "partial"}:
            warnings.extend(section.warnings)
    if any(section.coverage_status == "none" for section in evidence.sections):
        errors.append("One or more planned sections have no supporting evidence.")
    support_score = supported / total if total else 0.0
    return ArtifactContentValidation(
        passed=not errors,
        support_score=support_score,
        errors=list(dict.fromkeys(errors)),
        warnings=list(dict.fromkeys(warnings)),
    )


def _all_blocks(bundle: ArtifactContentBundle):
    for section in bundle.content.sections:
        yield f"content section {section.title}", section.blocks
    for section in bundle.paginated.sections:
        yield f"paginated section {section.title}", section.blocks
    for index, slide in enumerate(bundle.presentation.slides, start=1):
        yield f"slide {index} ({slide.title})", slide.blocks


def _used_evidence_ids(bundle: ArtifactContentBundle) -> set[str]:
    used: set[str] = set()
    for _location, blocks in _all_blocks(bundle):
        for block in blocks:
            used.update(block.evidence_ids)
            for item in block.list_items:
                used.update(item.evidence_ids)
            for entry in block.entries:
                used.update(entry.evidence_ids)
            if block.table is not None:
                for row in block.table.rows:
                    used.update(row.evidence_ids)
    return used


def _validate_block(
    blocks: list[ContentBlock],
    *,
    location: str,
    evidence_by_id: dict[str, object],
) -> tuple[list[str], int, int]:
    errors: list[str] = []
    supported = 0
    total = 0
    for index, block in enumerate(blocks, start=1):
        label = f"{location} block {index}"
        if block.kind in _FACTUAL_BLOCKS:
            total += 1
            if not block.evidence_ids:
                errors.append(f"{label} is factual but has no evidence IDs.")
            elif not set(block.evidence_ids).issubset(evidence_by_id):
                errors.append(f"{label} references unknown evidence IDs.")
            elif not _semantically_overlaps_text(_block_text(block), block.evidence_ids, evidence_by_id):
                errors.append(f"{label} has no lexical grounding in its cited evidence.")
            else:
                supported += 1
        if block.kind in _LIST_BLOCKS:
            for item_index, item_text, evidence_ids in _list_items(block):
                total += 1
                if not evidence_ids:
                    errors.append(f"{label} list item {item_index} is factual but has no evidence IDs.")
                elif not set(evidence_ids).issubset(evidence_by_id):
                    errors.append(f"{label} list item {item_index} references unknown evidence IDs.")
                elif not _semantically_overlaps_text(item_text, evidence_ids, evidence_by_id):
                    errors.append(f"{label} list item {item_index} has no lexical grounding in its cited evidence.")
                else:
                    supported += 1
        if block.kind == "key_value":
            for entry_index, entry in enumerate(block.entries, start=1):
                total += 1
                if not set(entry.evidence_ids).issubset(evidence_by_id):
                    errors.append(f"{label} key-value entry {entry_index} has invalid evidence IDs.")
                elif not _semantically_overlaps_text(f"{entry.key} {entry.value}", entry.evidence_ids, evidence_by_id):
                    errors.append(f"{label} key-value entry {entry_index} has no lexical grounding in its cited evidence.")
                else:
                    supported += 1
        if block.kind == "table" and block.table is not None:
            for row_index, row in enumerate(block.table.rows, start=1):
                total += 1
                if not set(row.evidence_ids).issubset(evidence_by_id):
                    errors.append(f"{label} table row {row_index} has invalid evidence IDs.")
                elif not _semantically_overlaps_text(" ".join(row.values), row.evidence_ids, evidence_by_id):
                    errors.append(f"{label} table row {row_index} has no lexical grounding in its cited evidence.")
                else:
                    supported += 1
    return errors, supported, total


def _block_text(block: ContentBlock) -> str:
    return block.text or ""


def _list_items(block: ContentBlock) -> list[tuple[int, str, list[str]]]:
    if block.list_items:
        return [
            (index, item.text, item.evidence_ids)
            for index, item in enumerate(block.list_items, start=1)
        ]
    return [
        (index, item, block.evidence_ids)
        for index, item in enumerate(block.items, start=1)
    ]


def _semantically_overlaps_text(text: str, evidence_ids: list[str], evidence_by_id: dict[str, object]) -> bool:
    claim_tokens = _tokens(text)
    if not claim_tokens:
        return True
    evidence_parts: list[str] = []
    for evidence_id in evidence_ids:
        record = evidence_by_id.get(evidence_id)
        if record is None:
            continue
        evidence_parts.append(str(getattr(record, "text", "") or ""))
        structured_fields = getattr(record, "structured_fields", {}) or {}
        evidence_parts.extend(str(value) for value in structured_fields.values())
    evidence_text = " ".join(evidence_parts)
    return bool(claim_tokens & _tokens(evidence_text))


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", value.lower())
        if token not in _STOPWORDS
    }
