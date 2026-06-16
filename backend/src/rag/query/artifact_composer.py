"""Compose evidence-backed semantic artifact content."""

from __future__ import annotations

from collections import OrderedDict
import re
from typing import Protocol

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from .artifact_models import (
    ArtifactContent,
    ArtifactFieldDefinition,
    ArtifactPlan,
    ArtifactTable,
    ArtifactTableRow,
    CoverageReport,
    EvidenceUnit,
    SemanticSection,
    SupportedClaim,
)
from .artifact_pipeline import citations_for_units
from .cancellation import QueryCancellationToken, call_with_optional_cancellation

_CITATION_RE = re.compile(r"\[([^\[\]\n]{1,200}:[^\[\]\n]{1,200})\]")
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_BULLET_RE = re.compile(r"^[-*]\s+")
_NUMBERED_RE = re.compile(r"^\d+[.)]\s+")


class ArtifactComposerClient(Protocol):
    def answer(
        self,
        *,
        question: str,
        contexts: list[str],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...


def compose_artifact_content(
    *,
    plan: ArtifactPlan,
    units: tuple[EvidenceUnit, ...],
    coverage: CoverageReport,
    ollama: ArtifactComposerClient,
    cancellation_token: QueryCancellationToken | None = None,
) -> ArtifactContent:
    if plan.primary_operation in {"enumerate", "extract"}:
        return _compose_structured_content(plan=plan, units=units, coverage=coverage)
    return _compose_narrative_content(
        plan=plan,
        units=units,
        coverage=coverage,
        ollama=ollama,
        cancellation_token=cancellation_token,
    )


def artifact_response_summary(content: ArtifactContent, *, requested_formats: tuple[str, ...]) -> str:
    table_rows = sum(len(table.rows) for section in content.sections for table in section.tables)
    formats = ", ".join(format_name.upper() for format_name in requested_formats)
    if table_rows:
        return (
            f"Prepared an evidence-backed {formats} artifact containing {table_rows} structured "
            f"record{'s' if table_rows != 1 else ''}."
        )
    return f"Prepared an evidence-backed {formats} artifact with {len(content.sections)} section(s)."


def _compose_structured_content(
    *,
    plan: ArtifactPlan,
    units: tuple[EvidenceUnit, ...],
    coverage: CoverageReport,
) -> ArtifactContent:
    grouped: OrderedDict[str, list[EvidenceUnit]] = OrderedDict()
    for unit in units:
        key = unit.table_title or plan.tasks[0].target_section
        grouped.setdefault(key, []).append(unit)
    tables: list[ArtifactTable] = []
    claims: list[SupportedClaim] = []
    for table_index, (table_title, table_units) in enumerate(grouped.items(), start=1):
        fields = _field_definitions(table_units)
        rows: list[ArtifactTableRow] = []
        seen_rows: set[tuple[tuple[str, str | None], ...]] = set()
        for row_index, unit in enumerate(table_units, start=1):
            values = _row_values(unit, fields)
            if not any(value for _name, value in values) or values in seen_rows:
                continue
            seen_rows.add(values)
            rows.append(ArtifactTableRow(values=values, evidence_ids=(unit.evidence_id,)))
            claim_text = "; ".join(
                f"{field.label}: {value}"
                for field in fields
                if (value := dict(values).get(field.name))
            )
            claims.append(
                SupportedClaim(
                    claim_id=f"claim_{table_index}_{row_index}",
                    text=claim_text,
                    evidence_ids=(unit.evidence_id,),
                )
            )
        if rows:
            tables.append(ArtifactTable(title=table_title, fields=fields, rows=tuple(rows)))
    warnings = tuple(coverage.warnings)
    return ArtifactContent(
        title=_title_from_objective(plan.objective),
        purpose=plan.objective,
        sections=(
            SemanticSection(
                heading=plan.tasks[0].target_section,
                tables=tuple(tables),
                claim_ids=tuple(claim.claim_id for claim in claims),
            ),
        ),
        claims=tuple(claims),
        citations=citations_for_units(units),
        coverage=coverage,
        warnings=warnings,
        metadata={
            "artifact_type": plan.artifact_type,
            "operations": ",".join(plan.operations),
        },
    )


def _compose_narrative_content(
    *,
    plan: ArtifactPlan,
    units: tuple[EvidenceUnit, ...],
    coverage: CoverageReport,
    ollama: ArtifactComposerClient,
    cancellation_token: QueryCancellationToken | None,
) -> ArtifactContent:
    contexts = [
        f"[{unit.doc_id}:{unit.chunk_id}]\n"
        f"Document: {unit.doc_title}\n"
        f"Location: {_location_text(unit)}\n"
        f"{unit.text}"
        for unit in units
    ]
    question = _composition_prompt(plan)
    answer = call_with_optional_cancellation(
        ollama.answer,
        cancellation_token,
        question=question,
        contexts=contexts,
    )
    sections, claims = _sections_from_answer(answer, units, default_heading=plan.tasks[0].target_section)
    return ArtifactContent(
        title=_title_from_objective(plan.objective),
        purpose=plan.objective,
        sections=sections,
        claims=claims,
        citations=citations_for_units(units),
        coverage=coverage,
        warnings=tuple(coverage.warnings),
        metadata={
            "artifact_type": plan.artifact_type,
            "operations": ",".join(plan.operations),
        },
    )


def _field_definitions(units: list[EvidenceUnit]) -> tuple[ArtifactFieldDefinition, ...]:
    labels: OrderedDict[str, str] = OrderedDict()
    include_item = any(unit.row_label for unit in units)
    if include_item:
        labels["item"] = "Item"
    for unit in units:
        for label, _value in unit.structured_fields:
            name = _field_name(label)
            labels.setdefault(name, label)
    return tuple(
        ArtifactFieldDefinition(name=name, label=label, required=index == 0)
        for index, (name, label) in enumerate(labels.items())
    )


def _row_values(
    unit: EvidenceUnit,
    fields: tuple[ArtifactFieldDefinition, ...],
) -> tuple[tuple[str, str | None], ...]:
    source_values = {_field_name(label): value for label, value in unit.structured_fields}
    if unit.row_label:
        source_values.setdefault("item", unit.row_label)
    return tuple((field.name, source_values.get(field.name)) for field in fields)


def _sections_from_answer(
    answer: str,
    units: tuple[EvidenceUnit, ...],
    *,
    default_heading: str,
) -> tuple[tuple[SemanticSection, ...], tuple[SupportedClaim, ...]]:
    sections: list[SemanticSection] = []
    claims: list[SupportedClaim] = []
    heading = default_heading
    paragraphs: list[str] = []
    bullets: list[str] = []
    section_claim_ids: list[str] = []

    def flush() -> None:
        nonlocal paragraphs, bullets, section_claim_ids
        if paragraphs or bullets:
            sections.append(
                SemanticSection(
                    heading=heading,
                    paragraphs=tuple(paragraphs),
                    bullets=tuple(bullets),
                    claim_ids=tuple(section_claim_ids),
                )
            )
        paragraphs = []
        bullets = []
        section_claim_ids = []

    for raw_line in answer.replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _HEADING_RE.match(line):
            flush()
            heading = _HEADING_RE.sub("", line).strip() or default_heading
            continue
        is_bullet = bool(_BULLET_RE.match(line) or _NUMBERED_RE.match(line))
        clean_line = _NUMBERED_RE.sub("", _BULLET_RE.sub("", line)).strip()
        evidence_ids = _evidence_ids_for_text(clean_line, units)
        claim_id = f"claim_{len(claims) + 1}"
        claims.append(
            SupportedClaim(
                claim_id=claim_id,
                text=clean_line,
                evidence_ids=evidence_ids,
                support_status="supported" if evidence_ids else "unsupported",
            )
        )
        section_claim_ids.append(claim_id)
        (bullets if is_bullet else paragraphs).append(clean_line)
    flush()
    return tuple(sections), tuple(claims)


def _evidence_ids_for_text(text: str, units: tuple[EvidenceUnit, ...]) -> tuple[str, ...]:
    labels = {f"{unit.doc_id}:{unit.chunk_id}": unit.evidence_id for unit in units}
    explicit = tuple(
        labels[label]
        for label in _CITATION_RE.findall(text)
        if label in labels
    )
    if explicit:
        return tuple(dict.fromkeys(explicit))
    text_tokens = normalized_match_tokens(_CITATION_RE.sub("", text))
    scored = [
        (len(text_tokens & normalized_match_tokens(unit.text)), unit)
        for unit in units
    ]
    score, best = max(scored, default=(0, None), key=lambda item: item[0])
    return (best.evidence_id,) if best is not None and score >= min(2, max(1, len(text_tokens))) else ()


def _composition_prompt(plan: ArtifactPlan) -> str:
    operations = ", ".join(plan.operations)
    return (
        f"Create semantic content for a {plan.artifact_type}. Objective: {plan.objective}. "
        f"Required operations: {operations}. Use only the supplied evidence. "
        "Organize the result with concise Markdown headings and bullets where useful. "
        "Cite every factual sentence or bullet with the exact evidence label shown in the context. "
        "Do not discuss file formatting, generation, or these instructions."
    )


def _location_text(unit: EvidenceUnit) -> str:
    start = unit.location.page_start
    end = unit.location.page_end
    if start is None:
        return "location unavailable"
    if end is not None and end != start:
        return f"pages {start}-{end}"
    return f"page {start}"


def _field_name(label: str) -> str:
    candidate = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return candidate[:64] or "value"


def _title_from_objective(objective: str) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", objective)
    return " ".join(words[:12]).title() if words else "Evidence Report"
