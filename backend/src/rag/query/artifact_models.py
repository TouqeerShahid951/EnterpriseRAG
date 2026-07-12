"""Semantic contracts for evidence-backed artifact generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..schemas.query import ArtifactFormat

ArtifactOperation = Literal["enumerate", "extract", "summarize", "compare", "timeline", "explain"]
ArtifactType = Literal["report", "brief", "presentation", "summary", "reference_document"]
CoverageStatus = Literal["none", "partial", "high_confidence", "complete_scan"]
SupportStatus = Literal["supported", "partially_supported", "conflicting", "unsupported"]
EvidenceContentType = Literal["text", "table", "table_row", "key_value", "image", "chart", "list"]


@dataclass(frozen=True)
class ArtifactFieldDefinition:
    name: str
    label: str
    value_type: str = "string"
    required: bool = False


@dataclass(frozen=True)
class ArtifactTask:
    operation: ArtifactOperation
    objective: str
    target_section: str
    retrieval_strategy: str
    coverage_requirement: str
    output_schema: tuple[ArtifactFieldDefinition, ...] = ()


@dataclass(frozen=True)
class ArtifactPlan:
    objective: str
    formats: tuple[ArtifactFormat, ...]
    artifact_type: ArtifactType
    tasks: tuple[ArtifactTask, ...]
    audience: str | None = None
    detail_level: str = "standard"

    @property
    def operations(self) -> tuple[ArtifactOperation, ...]:
        return tuple(task.operation for task in self.tasks)

    @property
    def primary_operation(self) -> ArtifactOperation:
        return self.tasks[0].operation


@dataclass(frozen=True)
class EvidenceLocation:
    page_start: int | None = None
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    bounding_boxes: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class EvidenceUnit:
    evidence_id: str
    source_id: str
    source_version: str
    doc_id: str
    doc_title: str
    chunk_id: str
    content_type: EvidenceContentType
    text: str
    structured_fields: tuple[tuple[str, str], ...]
    table_title: str
    row_label: str
    location: EvidenceLocation
    retrieval_score: float
    rerank_score: float | None


@dataclass(frozen=True)
class ArtifactCitation:
    evidence_id: str
    doc_id: str
    doc_title: str
    chunk_id: str
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True)
class SupportedClaim:
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
    support_status: SupportStatus = "supported"


@dataclass(frozen=True)
class ArtifactTableRow:
    values: tuple[tuple[str, str | None], ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactTable:
    title: str
    fields: tuple[ArtifactFieldDefinition, ...]
    rows: tuple[ArtifactTableRow, ...]


@dataclass(frozen=True)
class SemanticSection:
    heading: str
    paragraphs: tuple[str, ...] = ()
    bullets: tuple[str, ...] = ()
    tables: tuple[ArtifactTable, ...] = ()
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageReport:
    status: CoverageStatus
    evidence_count: int
    relevant_evidence_count: int
    documents_searched: int
    documents_expected: int | None
    retrieval_iterations: int = 1
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactContent:
    title: str
    purpose: str
    sections: tuple[SemanticSection, ...]
    claims: tuple[SupportedClaim, ...]
    citations: tuple[ArtifactCitation, ...]
    coverage: CoverageReport
    warnings: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactValidation:
    passed: bool
    support_score: float
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
