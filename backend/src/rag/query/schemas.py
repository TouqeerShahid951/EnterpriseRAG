from typing import Any, Literal

from pydantic import Field, model_validator

from ..artifact_jobs.schemas import ArtifactJobSummary, GeneratedArtifact
from ..schemas.common import ContractModel
from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from ..shared.contracts.evidence import (
    ConflictPair as ConflictPair,
    EvidenceField as EvidenceField,
    EvidenceWindow as EvidenceWindow,
    HighlightRange as HighlightRange,
    SourceAnchor as SourceAnchor,
    SourceRegion as SourceRegion,
)

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
