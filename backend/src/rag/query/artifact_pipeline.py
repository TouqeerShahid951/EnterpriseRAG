"""Planning, evidence adaptation, and validation for generated artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from .artifact_intent import ArtifactRequest
from .artifact_models import (
    ArtifactCitation,
    ArtifactContent,
    ArtifactOperation,
    ArtifactPlan,
    ArtifactTask,
    ArtifactType,
    ArtifactValidation,
    CoverageReport,
    EvidenceContentType,
    EvidenceLocation,
    EvidenceUnit,
)
from .qdrant import SearchHit

_PLANNING_STOPWORDS = {
    "a",
    "all",
    "an",
    "and",
    "artifact",
    "create",
    "document",
    "documents",
    "file",
    "for",
    "from",
    "generate",
    "in",
    "into",
    "list",
    "make",
    "of",
    "on",
    "output",
    "prepare",
    "produce",
    "report",
    "show",
    "summarize",
    "summary",
    "the",
    "to",
    "with",
}
_OPERATION_PATTERNS: tuple[tuple[ArtifactOperation, re.Pattern[str]], ...] = (
    ("compare", re.compile(r"\b(?:compare|comparison|versus|vs\.?|differences?)\b", re.IGNORECASE)),
    ("timeline", re.compile(r"\b(?:timeline|chronolog|history|over\s+time|amendments?)\b", re.IGNORECASE)),
    ("enumerate", re.compile(r"\b(?:list|listing|listed|enumerate|inventory|all\s+the|every)\b", re.IGNORECASE)),
    ("extract", re.compile(r"\b(?:extract|fields?|details?|values?|entities)\b", re.IGNORECASE)),
    ("summarize", re.compile(r"\b(?:summari[sz]e|summary|overview|brief)\b", re.IGNORECASE)),
    ("explain", re.compile(r"\b(?:explain|describe|how|why)\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class ArtifactEvidenceAssessment:
    units: tuple[EvidenceUnit, ...]
    coverage: CoverageReport
    relevance_coverage: float

    @property
    def is_weak(self) -> bool:
        return not self.units or self.coverage.status == "none"


def plan_artifact_request(request: ArtifactRequest, *, document_ids: list[str]) -> ArtifactPlan:
    operations = _operations_for(request.content_query)
    artifact_type = _artifact_type(request, operations)
    tasks = tuple(
        ArtifactTask(
            operation=operation,
            objective=request.content_query,
            target_section=_target_section(operation),
            retrieval_strategy=_retrieval_strategy(operation),
            coverage_requirement=_coverage_requirement(operation, document_ids=document_ids),
        )
        for operation in operations
    )
    return ArtifactPlan(
        objective=request.content_query,
        formats=request.formats,
        artifact_type=artifact_type,
        tasks=tasks,
    )


def assess_artifact_evidence(
    plan: ArtifactPlan,
    hits: list[SearchHit],
    *,
    document_ids: list[str],
) -> ArtifactEvidenceAssessment:
    units = tuple(evidence_unit_from_hit(hit) for hit in hits)
    scoped = bool(document_ids)
    relevant = tuple(unit for unit in units if _is_relevant(unit, plan))
    if plan.primary_operation in {"enumerate", "extract"}:
        relevant = tuple(
            unit
            for unit in relevant
            if unit.content_type in {"table_row", "key_value"} and bool(unit.structured_fields)
        )
    distinct_docs = {unit.doc_id for unit in units}
    expected_docs = len(set(document_ids)) if scoped else None
    relevance_coverage = len(relevant) / len(units) if units else 0.0
    status = "none"
    warnings: list[str] = []
    if relevant:
        if scoped and distinct_docs.issuperset(set(document_ids)):
            status = "high_confidence"
        elif relevance_coverage >= 0.5:
            status = "high_confidence"
        else:
            status = "partial"
            warnings.append("Only part of the retrieved evidence was relevant to the artifact objective.")
    else:
        warnings.append("No retrieved evidence was relevant to the artifact objective.")
    if _operation_requires_scan(plan.primary_operation):
        warnings.append(
            "Coverage reflects retrieved and expanded evidence; exhaustive completeness requires a full authorized-scope scan."
        )
    return ArtifactEvidenceAssessment(
        units=relevant,
        relevance_coverage=relevance_coverage,
        coverage=CoverageReport(
            status=status,  # type: ignore[arg-type]
            evidence_count=len(units),
            relevant_evidence_count=len(relevant),
            documents_searched=len(distinct_docs),
            documents_expected=expected_docs,
            warnings=tuple(warnings),
        ),
    )


def evidence_unit_from_hit(hit: SearchHit) -> EvidenceUnit:
    payload = hit.payload
    source_regions = payload.get("source_regions")
    boxes: list[tuple[float, float, float, float]] = []
    if isinstance(source_regions, list):
        for region in source_regions:
            if not isinstance(region, dict):
                continue
            bbox = region.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(value, int | float) for value in bbox):
                boxes.append(tuple(float(value) for value in bbox))  # type: ignore[arg-type]
    fields: list[tuple[str, str]] = []
    raw_fields = payload.get("structured_fields")
    if isinstance(raw_fields, list):
        for field in raw_fields:
            if not isinstance(field, dict):
                continue
            label = field.get("label")
            value = field.get("value")
            if isinstance(label, str) and label.strip() and isinstance(value, str) and value.strip():
                fields.append((label.strip(), value.strip()))
    doc_id = _string(payload.get("doc_id")) or hit.point_id
    chunk_id = _string(payload.get("chunk_id")) or hit.point_id
    return EvidenceUnit(
        evidence_id=_evidence_id(doc_id, chunk_id),
        source_id=_string(payload.get("source_id")) or doc_id,
        source_version=_string(payload.get("content_hash")) or "current",
        doc_id=doc_id,
        doc_title=_string(payload.get("doc_title")) or "Untitled",
        chunk_id=chunk_id,
        content_type=_content_type(payload),
        text=_string(payload.get("text")) or "",
        structured_fields=tuple(fields),
        table_title=_string(payload.get("table_title")) or "",
        row_label=_string(payload.get("table_row_label")) or "",
        location=EvidenceLocation(
            page_start=_integer(payload.get("page_start")) or _integer(payload.get("page")),
            page_end=_integer(payload.get("page_end")) or _integer(payload.get("page_start")) or _integer(payload.get("page")),
            section_path=tuple(str(part) for part in payload.get("section_path", []) if str(part).strip())
            if isinstance(payload.get("section_path"), list)
            else (),
            bounding_boxes=tuple(boxes),
        ),
        retrieval_score=float(hit.score),
        rerank_score=_float(payload.get("_rerank_score")),
    )


def citations_for_units(units: tuple[EvidenceUnit, ...]) -> tuple[ArtifactCitation, ...]:
    return tuple(
        ArtifactCitation(
            evidence_id=unit.evidence_id,
            doc_id=unit.doc_id,
            doc_title=unit.doc_title,
            chunk_id=unit.chunk_id,
            page_start=unit.location.page_start,
            page_end=unit.location.page_end,
        )
        for unit in units
    )


def validate_artifact_content(content: ArtifactContent, plan: ArtifactPlan) -> ArtifactValidation:
    errors: list[str] = []
    warnings = list(content.warnings)
    citation_ids = {citation.evidence_id for citation in content.citations}
    supported = 0
    total = 0
    for claim in content.claims:
        total += 1
        if claim.support_status != "supported" or not claim.evidence_ids:
            errors.append(f"Claim {claim.claim_id} is not fully supported.")
            continue
        if not set(claim.evidence_ids).issubset(citation_ids):
            errors.append(f"Claim {claim.claim_id} references unknown evidence.")
            continue
        supported += 1
    row_count = 0
    for section in content.sections:
        for table in section.tables:
            for row in table.rows:
                row_count += 1
                if not row.evidence_ids or not set(row.evidence_ids).issubset(citation_ids):
                    errors.append(f"Table row {row_count} does not have valid evidence.")
    if not content.sections:
        errors.append("Artifact content has no sections.")
    if plan.primary_operation in {"enumerate", "extract"} and row_count == 0:
        errors.append("Structured artifact contains no evidence-backed rows.")
    if content.coverage.status == "none":
        errors.append("Artifact coverage contains no relevant evidence.")
    support_score = supported / total if total else (1.0 if row_count > 0 else 0.0)
    return ArtifactValidation(
        passed=not errors,
        support_score=support_score,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _operations_for(query: str) -> tuple[ArtifactOperation, ...]:
    operations = tuple(operation for operation, pattern in _OPERATION_PATTERNS if pattern.search(query))
    return operations or ("summarize",)


def _artifact_type(request: ArtifactRequest, operations: tuple[ArtifactOperation, ...]) -> ArtifactType:
    if request.formats == ("pptx",):
        return "presentation"
    if operations == ("summarize",):
        return "summary"
    if operations[0] in {"enumerate", "extract"}:
        return "reference_document"
    return "report"


def _target_section(operation: ArtifactOperation) -> str:
    return {
        "enumerate": "Items",
        "extract": "Extracted Information",
        "summarize": "Summary",
        "compare": "Comparison",
        "timeline": "Timeline",
        "explain": "Explanation",
    }[operation]


def _retrieval_strategy(operation: ArtifactOperation) -> str:
    return {
        "enumerate": "structured_rows_exhaustive",
        "extract": "structured_fields_first",
        "summarize": "ordered_sections",
        "compare": "grouped_multi_query",
        "timeline": "date_bearing_evidence",
        "explain": "focused_evidence",
    }[operation]


def _coverage_requirement(operation: ArtifactOperation, *, document_ids: list[str]) -> str:
    if operation in {"enumerate", "extract"}:
        return "complete_authorized_scope" if document_ids else "coverage_estimate"
    return "all_selected_documents" if document_ids else "relevant_evidence"


def _is_relevant(unit: EvidenceUnit, plan: ArtifactPlan) -> bool:
    query_tokens = _objective_tokens(plan.objective)
    if not query_tokens:
        return True
    if plan.primary_operation in {"enumerate", "extract"}:
        document_tokens = normalized_match_tokens(unit.doc_title)
        subject_tokens = query_tokens - document_tokens or query_tokens
        schema_tokens = normalized_match_tokens(
            " ".join(
                (
                    unit.table_title,
                    " ".join(label for label, _value in unit.structured_fields),
                )
            )
        )
        return bool(subject_tokens & schema_tokens)
    evidence_tokens = normalized_match_tokens(
        " ".join(
            (
                unit.doc_title,
                unit.table_title,
                unit.row_label,
                unit.text,
                " ".join(f"{label} {value}" for label, value in unit.structured_fields),
                " ".join(unit.location.section_path),
            )
        )
    )
    overlap = query_tokens & evidence_tokens
    coverage = len(overlap) / len(query_tokens)
    return coverage >= 0.25 or len(overlap) >= 2


def _objective_tokens(objective: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(objective)
        if len(token) > 2 and token not in _PLANNING_STOPWORDS
    }


def _operation_requires_scan(operation: ArtifactOperation) -> bool:
    return operation in {"enumerate", "extract"}


def _content_type(payload: dict[str, object]) -> EvidenceContentType:
    chunk_type = _string(payload.get("chunk_type"))
    structured_kind = _string(payload.get("structured_kind"))
    if chunk_type == "table_row" or structured_kind == "table_row":
        return "table_row"
    if chunk_type == "table":
        return "table"
    if chunk_type == "kv_record" or structured_kind == "kv_record":
        return "key_value"
    if chunk_type in {"image", "figure"}:
        return "image"
    if chunk_type == "chart":
        return "chart"
    if chunk_type == "list":
        return "list"
    return "text"


def _evidence_id(doc_id: str, chunk_id: str) -> str:
    digest = sha256(f"{doc_id}:{chunk_id}".encode("utf-8")).hexdigest()[:16]
    return f"ev_{digest}"


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _integer(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None
