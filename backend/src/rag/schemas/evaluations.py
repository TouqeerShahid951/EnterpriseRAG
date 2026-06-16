from typing import Any, Literal

from pydantic import Field, model_validator

from .common import ContractModel


EvaluationRunStatus = Literal["queued", "running", "complete", "partial", "failed", "cancelled"]
EvaluationFailureStage = Literal[
    "dataset",
    "ingestion/indexing",
    "retrieval",
    "reranking/source_selection",
    "answer_content",
    "citation",
    "faithfulness",
    "degradation",
    "runtime",
    "latency",
]


class EvaluationCase(ContractModel):
    id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    question_type: str | None = None
    difficulty: str | None = None
    expected_answer: str | None = None
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    expected_source_docs: list[str] = Field(default_factory=list)
    acceptable_source_pages: list[int] = Field(default_factory=list)
    min_sources: int = Field(default=0, ge=0)
    must_cite_source: bool = False
    min_faithfulness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    allow_degraded: bool = False
    latency_threshold_ms: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationDatasetSummary(ContractModel):
    id: str
    name: str
    description: str | None = None
    source_format: str
    case_count: int
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class EvaluationDatasetDetail(EvaluationDatasetSummary):
    cases: list[EvaluationCase]
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationDatasetListResponse(ContractModel):
    items: list[EvaluationDatasetSummary]
    total: int


class EvaluationDatasetImportRequest(ContractModel):
    name: str | None = Field(default=None, max_length=160)
    content: str = Field(..., min_length=1)
    source_format: Literal["auto", "json", "jsonl"] = "auto"


class EvaluationRunCreateRequest(ContractModel):
    dataset_id: str = Field(..., min_length=1)
    group_path: str | None = Field(default=None, min_length=1)
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    case_ids: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_selection(self) -> "EvaluationRunCreateRequest":
        if self.case_ids and self.limit is not None:
            raise ValueError("case_ids and limit cannot be combined")
        return self


class EvaluationRunSummary(ContractModel):
    id: str
    dataset_id: str
    dataset_name: str
    status: EvaluationRunStatus
    stage: str
    progress_pct: int = Field(..., ge=0, le=100)
    case_count: int = Field(..., ge=0)
    completed_count: int = Field(..., ge=0)
    passed_count: int = Field(..., ge=0)
    failed_count: int = Field(..., ge=0)
    summary: dict[str, Any] = Field(default_factory=dict)
    group_path: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    last_heartbeat_at: str | None = None


class EvaluationCaseResult(ContractModel):
    id: str
    run_id: str
    case_id: str
    case_index: int
    question: str
    status: Literal["ok", "error"]
    passed: bool
    primary_failure_stage: EvaluationFailureStage | None = None
    failure_stages: list[EvaluationFailureStage] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)
    answer: str = ""
    sources: list[dict[str, Any]] = Field(default_factory=list)
    diagnostic: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    node_timings: list[dict[str, Any]] = Field(default_factory=list)
    faithfulness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    faithfulness_status: str | None = None
    unfounded_claims: list[str] = Field(default_factory=list)
    degraded: bool = False
    degraded_reason: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    error_message: str | None = None
    created_at: str | None = None


class EvaluationRunDetail(EvaluationRunSummary):
    cases: list[EvaluationCaseResult] = Field(default_factory=list)
    rag_config_snapshot: dict[str, Any] = Field(default_factory=dict)
    failure_breakdown: dict[str, int] = Field(default_factory=dict)
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1)


class EvaluationRunListResponse(ContractModel):
    items: list[EvaluationRunSummary]
    total: int


class EvaluationRunMutationResponse(ContractModel):
    run: EvaluationRunSummary
