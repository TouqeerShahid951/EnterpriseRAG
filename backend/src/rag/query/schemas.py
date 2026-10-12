from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from ..artifact_jobs.schemas import ArtifactJobSummary, GeneratedArtifact
from rag.shared.contracts.http import ContractModel
from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from ..shared.contracts.evidence import (
    CitationVerification,
    CitationTarget as CitationTarget,
    ConflictPair as ConflictPair,
    EvidenceField as EvidenceField,
    EvidenceWindow as EvidenceWindow,
    HighlightRange as HighlightRange,
    SourceAnchor as SourceAnchor,
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
AnswerStatus = Literal["complete", "partial", "clarification", "abstained"]
CoverageCompleteness = Literal["complete", "partial", "unknown", "not_applicable"]
OperationalFailureStage = Literal["selection", "generation", "validation", "execution"]
QuerySourceId = Annotated[str, Field(min_length=1, max_length=240)]


class QueryRequest(ContractModel):
    query: str = Field(..., min_length=1)
    session_id: str | None = None
    client_request_id: str | None = Field(default=None, min_length=1, max_length=120)
    reply_to_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    group_path: str | None = Field(default=None, min_length=1)
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    source_mode: QuerySourceMode = "auto"
    query_source_id: QuerySourceId | None = None
    query_source_ids: list[QuerySourceId] = Field(default_factory=list, max_length=3)
    allow_source_expansion: bool = False
    continue_source_clarification: bool = False

    @model_validator(mode="after")
    def validate_source_scope(self) -> "QueryRequest":
        source_ids = self.effective_query_source_ids
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("query_source_ids must not contain duplicates")
        if self.query_source_id and self.query_source_ids:
            if self.query_source_id != self.query_source_ids[0]:
                raise ValueError("query_source_id must match the first query_source_ids item")
        if self.source_mode == "corpus_only" and source_ids:
            raise ValueError("corpus_only queries cannot specify database sources")
        if self.source_mode == "db_only" and self.document_ids:
            raise ValueError("db_only queries cannot specify document_ids")
        if self.continue_source_clarification and not (
            self.client_request_id
            and len(source_ids) == 1
            and self.source_mode in {"db_only", "hybrid"}
        ):
            raise ValueError(
                "source clarification continuation requires a database source and client_request_id"
            )
        if self.reply_to_turn_id and not self.session_id:
            raise ValueError("reply_to_turn_id requires a session_id")
        return self

    @property
    def effective_query_source_ids(self) -> tuple[str, ...]:
        if self.query_source_ids:
            return tuple(self.query_source_ids)
        return (self.query_source_id,) if self.query_source_id else ()


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
    phase_timings_ms: dict[str, int] = Field(default_factory=dict)


class QueryCoverage(ContractModel):
    required_slots: list[str] = Field(default_factory=list)
    covered_slots: list[str] = Field(default_factory=list)
    completeness: CoverageCompleteness = "not_applicable"
    warnings: list[str] = Field(default_factory=list)


class QueryOperationalFailure(ContractModel):
    stage: OperationalFailureStage
    code: str
    retryable: bool
    source_id: str | None = None
    message: str


class QuerySourceClarificationOption(ContractModel):
    source_id: str
    name: str
    description: str | None = None


class QuerySourceClarification(ContractModel):
    question: str
    options: list[QuerySourceClarificationOption] = Field(default_factory=list)


class RAGResponse(ContractModel):
    trace_id: str
    answer: str
    answer_status: AnswerStatus = "complete"
    coverage: QueryCoverage = Field(default_factory=QueryCoverage)
    sources: list[SourceAnchor] = Field(default_factory=list)
    citation_verification: CitationVerification | None = None
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
    operational_failures: list[QueryOperationalFailure] = Field(default_factory=list)
    source_mode: str | None = None
    query_source_id: str | None = None
    source_decision_reason: str | None = None
    source_expansion: SourceExpansion | None = None
    source_clarification: QuerySourceClarification | None = None


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


SseEventType = Literal["trace", "retrieval_stage", "intent", "token", "source", "artifact", "artifact_job", "warning", "done", "verified", "error"]


class QueryStreamEvent(ContractModel):
    event: SseEventType
    data: dict[str, object] = Field(default_factory=dict)
