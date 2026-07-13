from typing import Any, Literal

from pydantic import Field, model_validator

from ..artifact_jobs.schemas import (
    ArtifactJobStageProgress as ArtifactJobStageProgress,
    ArtifactJobSummary as ArtifactJobSummary,
    GeneratedArtifact as GeneratedArtifact,
)
from ..artifact_jobs.types import (
    ArtifactFormat as ArtifactFormat,
    ArtifactJobProgressUnit as ArtifactJobProgressUnit,
    ArtifactJobStatus as ArtifactJobStatus,
)
from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .common import ContractModel

QueryIntent = Literal[
    "factual_simple",
    "multi_hop",
    "temporal",
    "contradictory",
    "aggregation",
    "conversational",
]
FaithfulnessStatus = Literal["pending", "checked", "skipped", "failed"]
QuerySourceMode = Literal["auto", "corpus_only", "db_only", "hybrid"]
QuerySourceKind = Literal["connector_schema_catalog"]


class HighlightRange(ContractModel):
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "HighlightRange":
        if self.end <= self.start:
            raise ValueError("highlight range end must be greater than start")
        return self


class SourceRegion(ContractModel):
    page: int | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    text: str = ""
    region_type: str = "text"
    confidence: float | None = None
    image_asset_id: str | None = None
    image_source_kind: str | None = None
    extraction_method: str | None = None


class EvidenceField(ContractModel):
    label: str
    value: str
    supports_claim: bool = False


class EvidenceWindow(ContractModel):
    claim_id: str
    claim: str
    kind: Literal["text", "table_row"] = "text"
    passage: str
    highlight_ranges: list[HighlightRange] = Field(default_factory=list)
    support_status: Literal["verified", "semantic_fallback"]
    support_score: float = Field(..., ge=0.0, le=1.0)
    source_start: int = Field(..., ge=0)
    source_end: int = Field(..., ge=0)
    quote_start: int | None = Field(default=None, ge=0)
    quote_end: int | None = Field(default=None, ge=0)
    truncated_start: bool = False
    truncated_end: bool = False
    table_title: str | None = None
    fields: list[EvidenceField] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_offsets(self) -> "EvidenceWindow":
        if self.source_end <= self.source_start:
            raise ValueError("evidence source end must be greater than start")
        if (self.quote_start is None) != (self.quote_end is None):
            raise ValueError("evidence quote offsets must be provided together")
        if self.quote_start is not None and self.quote_end is not None:
            if self.quote_end <= self.quote_start:
                raise ValueError("evidence quote end must be greater than start")
            if self.quote_start < self.source_start or self.quote_end > self.source_end:
                raise ValueError("evidence quote must be contained by the source window")
        if any(item.end > len(self.passage) for item in self.highlight_ranges):
            raise ValueError("evidence highlight must be contained by the passage")
        return self


class SourceAnchor(ContractModel):
    doc_id: str
    doc_title: str
    chunk_id: str
    page: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    excerpt: str
    group_path: str
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    effective_date: str | None = None
    highlight_ranges: list[HighlightRange] = Field(default_factory=list)
    source_regions: list[SourceRegion] = Field(default_factory=list)
    evidence_windows: list[EvidenceWindow] = Field(default_factory=list)
    attribution_status: Literal["pending", "complete", "unavailable"] = "pending"
    attribution_kind: Literal["text", "table_row"] = Field(default="text", exclude=True)
    attribution_table_title: str = Field(default="", exclude=True)
    attribution_fields: list[EvidenceField] = Field(default_factory=list, exclude=True)


class ConflictPair(ContractModel):
    claim_a_id: str
    claim_b_id: str
    doc_a_id: str
    doc_b_id: str
    chunk_a_id: str
    chunk_b_id: str
    entity: str
    attribute: str
    value_a: str
    value_b: str
    effective_date_a: str | None = None
    effective_date_b: str | None = None
    source_a: SourceAnchor
    source_b: SourceAnchor


class QueryRequest(ContractModel):
    query: str = Field(..., min_length=1)
    session_id: str | None = None
    client_request_id: str | None = Field(default=None, min_length=1, max_length=120)
    group_path: str | None = Field(default=None, min_length=1)
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    source_mode: QuerySourceMode = "auto"
    query_source_id: str | None = Field(default=None, min_length=1, max_length=240)
    allow_source_expansion: bool = False

    @model_validator(mode="after")
    def validate_source_scope(self) -> "QueryRequest":
        if self.source_mode == "corpus_only" and self.query_source_id:
            raise ValueError("corpus_only queries cannot specify a query_source_id")
        if self.source_mode == "db_only" and self.document_ids:
            raise ValueError("db_only queries cannot specify document_ids")
        return self


class QuerySource(ContractModel):
    id: str
    kind: QuerySourceKind
    name: str
    description: str | None = None
    connector_type: str
    scope: Literal["database_scope"]
    group_path: str
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL


class QuerySourceListResponse(ContractModel):
    items: list[QuerySource] = Field(default_factory=list)
    total: int = Field(..., ge=0)


class SourceExpansion(ContractModel):
    available: bool = False
    reason: str
    suggested_source_mode: QuerySourceMode = "hybrid"


class QueryNodeTiming(ContractModel):
    node: str
    duration_ms: int = Field(..., ge=0)
    execution_mode: str | None = None
    detail: str | None = None


class RAGResponse(ContractModel):
    trace_id: str
    answer: str
    sources: list[SourceAnchor] = Field(default_factory=list)
    artifacts: list[GeneratedArtifact] = Field(default_factory=list)
    artifact_job: ArtifactJobSummary | None = None
    conflict_flag: bool
    conflict_detail: list[ConflictPair] | None = None
    faithfulness_score: float = Field(..., ge=0.0, le=1.0)
    faithfulness_status: FaithfulnessStatus = "checked"
    unfounded_claims: list[str] = Field(default_factory=list)
    intent: QueryIntent
    session_id: str
    latency_ms: int = Field(..., ge=0)
    node_timings: list[QueryNodeTiming] = Field(default_factory=list)
    degraded: bool
    degraded_reason: str | None = None
    source_mode: str | None = None
    source_decision_reason: str | None = None
    source_expansion: SourceExpansion | None = None


class ChatSession(ContractModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    turns: list[dict[str, Any]] = Field(default_factory=list)


class ChatSessionSummary(ContractModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    question_count: int = Field(default=0, ge=0)


class ChatSessionListResponse(ContractModel):
    items: list[ChatSessionSummary]
    total: int
    limit: int
    offset: int


SseEventType = Literal["trace", "intent", "token", "source", "artifact", "artifact_job", "warning", "done", "verified", "error"]


class QueryStreamEvent(ContractModel):
    event: SseEventType
    data: dict[str, object] = Field(default_factory=dict)
