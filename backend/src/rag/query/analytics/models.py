"""Transport-neutral contracts for query execution analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol


AnalyticsOrigin = Literal["chat", "query_tracker", "evaluation", "other_internal"]
AnalyticsWorkKind = Literal["answer", "artifact_submission"]
AnalyticsOutcome = Literal[
    "complete",
    "partial",
    "clarification",
    "abstained",
    "system_error",
    "access_denied",
    "cancelled",
    "interrupted",
    "artifact_submitted",
]
AnalyticsLifecycle = Literal["in_flight", "terminal"]
AnalyticsBucketSize = Literal["hour", "day"]
AnalyticsLineageStatus = Literal[
    "not_captured", "available", "truncated", "unavailable", "expired"
]


@dataclass(frozen=True, slots=True)
class AnalyticsBoundaryEvent:
    event_id: str
    occurred_at: datetime
    route_path: str
    status_code: int
    reason_code: str
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsExecutionRecord:
    execution_id: str
    trace_id: str
    session_id: str
    actor_id: str
    permission_version: int
    origin: AnalyticsOrigin
    work_kind: AnalyticsWorkKind
    group_path: str | None
    lifecycle: AnalyticsLifecycle
    started_at: datetime
    reconciliation_deadline_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    outcome: AnalyticsOutcome | None = None
    answer_status: str | None = None
    reason_code: str | None = None
    degraded: bool | None = None
    degraded_reason: str | None = None
    requested_source_mode: str | None = None
    resolved_source_mode: str | None = None
    initial_intent: str | None = None
    final_intent: str | None = None
    response_mode: str | None = None
    latency_ms: int | None = None
    verification_status: str | None = None
    verification_method: str | None = None
    faithfulness_score: float | None = None
    retry_count: int = 0
    route_reroute_count: int = 0
    retrieved_hit_count: int | None = None
    evidence_source_count: int | None = None
    cited_source_count: int | None = None
    max_retrieval_score: float | None = None
    max_rerank_score: float | None = None
    model_cohort: str | None = None
    configuration_digest: str | None = None
    application_image_digest: str | None = None
    cohort_snapshot: dict[str, object] | None = None
    retrieval_lineage_status: AnalyticsLineageStatus = "not_captured"
    retrieval_lineage: dict[str, object] | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsFilters:
    created_from: datetime
    created_to: datetime
    origin: AnalyticsOrigin | None = None
    work_kind: AnalyticsWorkKind | None = None
    actor_id: str | None = None
    group_path: str | None = None
    outcome: AnalyticsOutcome | None = None
    source_mode: str | None = None
    intent: str | None = None
    model_cohort: str | None = None
    configuration_digest: str | None = None
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsRate:
    numerator: int = 0
    denominator: int = 0

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator


@dataclass(frozen=True, slots=True)
class AnalyticsSummary:
    total_executions: int = 0
    terminal_executions: int = 0
    in_flight_executions: int = 0
    complete: int = 0
    partial: int = 0
    clarification: int = 0
    abstained: int = 0
    system_error: int = 0
    access_denied: int = 0
    cancelled: int = 0
    interrupted: int = 0
    artifact_submitted: int = 0
    answer_executions: int = 0
    unique_actor_count: int = 0
    verification_checked: int = 0
    verification_applicable: int = 0
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    complete_rate: AnalyticsRate = field(default_factory=AnalyticsRate)
    abstention_rate: AnalyticsRate = field(default_factory=AnalyticsRate)
    system_error_rate: AnalyticsRate = field(default_factory=AnalyticsRate)
    verification_coverage: AnalyticsRate = field(default_factory=AnalyticsRate)


@dataclass(frozen=True, slots=True)
class AnalyticsPage:
    items: tuple[AnalyticsExecutionRecord, ...] = ()
    total: int = 0


@dataclass(frozen=True, slots=True)
class AnalyticsSeriesBucket:
    started_at: datetime
    ended_at: datetime
    total_executions: int = 0
    answer_executions: int = 0
    complete: int = 0
    partial: int = 0
    clarification: int = 0
    abstained: int = 0
    system_error: int = 0
    access_denied: int = 0
    cancelled: int = 0
    interrupted: int = 0
    artifact_submitted: int = 0
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    verification_checked: int = 0
    verification_applicable: int = 0
    faithfulness_score_mean: float | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsSeries:
    bucket_size: AnalyticsBucketSize
    buckets: tuple[AnalyticsSeriesBucket, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalyticsScoreStats:
    count: int = 0
    mean: float | None = None
    p50: float | None = None
    p95: float | None = None
    buckets: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class AnalyticsCountStats:
    count: int = 0
    mean: float | None = None
    p50: float | None = None
    p95: float | None = None
    buckets: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class AnalyticsRankMovement:
    status: Literal["available", "unavailable"] = "unavailable"
    count: int = 0
    mean_absolute: float | None = None
    p50_absolute: float | None = None
    p95_absolute: float | None = None
    promoted: int = 0
    demoted: int = 0
    unchanged: int = 0


@dataclass(frozen=True, slots=True)
class AnalyticsEvidenceUtilization:
    status: Literal["available", "unavailable"] = "unavailable"
    execution_count: int = 0
    sent_source_count: int = 0
    cited_source_count: int = 0
    utilization_rate: float | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsStageDiagnostics:
    name: str
    execution_count: int = 0
    candidate_count: int = 0
    serialized_candidate_count: int = 0
    retrieval_score: AnalyticsScoreStats = field(default_factory=AnalyticsScoreStats)
    rerank_score: AnalyticsScoreStats = field(default_factory=AnalyticsScoreStats)
    adjusted_rerank_score: AnalyticsScoreStats = field(default_factory=AnalyticsScoreStats)


@dataclass(frozen=True, slots=True)
class AnalyticsTimingDiagnostics:
    node: str
    execution_count: int = 0
    duration_count: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsDocumentUsage:
    document_key: str
    document_title: str | None = None
    generation_id: str | None = None
    execution_count: int = 0
    candidate_count: int = 0


@dataclass(frozen=True, slots=True)
class AnalyticsTopKTurnover:
    status: Literal["available", "unavailable"] = "unavailable"
    comparable_attempt_count: int = 0
    mean_overlap: float | None = None
    p50_overlap: float | None = None
    p95_overlap: float | None = None
    mean_added: float | None = None
    mean_dropped: float | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsDocumentDiagnostics:
    status: Literal["available", "unavailable"] = "unavailable"
    documents_per_query: AnalyticsCountStats = field(default_factory=AnalyticsCountStats)
    top_documents: tuple[AnalyticsDocumentUsage, ...] = ()
    top_k_turnover: AnalyticsTopKTurnover = field(default_factory=AnalyticsTopKTurnover)


@dataclass(frozen=True, slots=True)
class AnalyticsCohortObservation:
    model_cohort: str
    configuration_digest: str
    application_image_digest: str | None = None
    execution_count: int = 0
    first_observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsClaimLedger:
    status: Literal["available", "unavailable"] = "unavailable"
    execution_count: int = 0
    applicable_claim_count: int = 0
    supported_claim_count: int = 0
    unsupported_claim_count: int = 0
    unknown_claim_count: int = 0
    cited_claim_count: int = 0
    uncited_claim_count: int = 0
    valid_quote_count: int = 0
    support_rate: AnalyticsRate = field(default_factory=AnalyticsRate)
    citation_coverage: AnalyticsRate = field(default_factory=AnalyticsRate)


@dataclass(frozen=True, slots=True)
class AnalyticsDiagnostics:
    capture_status_counts: tuple[tuple[str, int], ...] = ()
    stages: tuple[AnalyticsStageDiagnostics, ...] = ()
    timings: tuple[AnalyticsTimingDiagnostics, ...] = ()
    rank_movement: AnalyticsRankMovement = field(default_factory=AnalyticsRankMovement)
    evidence_utilization: AnalyticsEvidenceUtilization = field(
        default_factory=AnalyticsEvidenceUtilization
    )
    quality: "AnalyticsQualityDiagnostics" = field(
        default_factory=lambda: AnalyticsQualityDiagnostics()
    )
    documents: AnalyticsDocumentDiagnostics = field(
        default_factory=AnalyticsDocumentDiagnostics
    )
    cohorts: tuple[AnalyticsCohortObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalyticsQualityDiagnostics:
    status_counts: tuple[tuple[str, int], ...] = ()
    method_counts: tuple[tuple[str, int], ...] = ()
    support_status_counts: tuple[tuple[str, int], ...] = ()
    score: AnalyticsScoreStats = field(default_factory=AnalyticsScoreStats)
    checked_count: int = 0
    applicable_count: int = 0
    claim_ledger: AnalyticsClaimLedger = field(default_factory=AnalyticsClaimLedger)


@dataclass(frozen=True, slots=True)
class AnalyticsMaintenanceResult:
    reconciled_execution_count: int = 0
    deleted_execution_count: int = 0
    deleted_boundary_event_count: int = 0
    expired_lineage_count: int = 0


class AnalyticsExecutionRepository(Protocol):
    def record_boundary_event(self, event: AnalyticsBoundaryEvent) -> None: ...

    def start_execution(self, record: AnalyticsExecutionRecord) -> AnalyticsExecutionRecord: ...

    def finish_execution(
        self, execution_id: str, **updates: object
    ) -> AnalyticsExecutionRecord | None: ...

    def heartbeat_execution(self, execution_id: str, *, grace_seconds: int) -> bool: ...

    def get_execution(self, execution_id: str) -> AnalyticsExecutionRecord | None: ...

    def list_executions(
        self,
        *,
        filters: AnalyticsFilters,
        limit: int,
        offset: int,
    ) -> AnalyticsPage: ...

    def summarize_executions(self, *, filters: AnalyticsFilters) -> AnalyticsSummary: ...

    def series_executions(
        self,
        *,
        filters: AnalyticsFilters,
        bucket_size: AnalyticsBucketSize,
    ) -> AnalyticsSeries: ...

    def diagnose_executions(self, *, filters: AnalyticsFilters) -> AnalyticsDiagnostics: ...

    def maintain(
        self,
        *,
        as_of: datetime,
        retention_before: datetime,
        batch_size: int,
        lineage_before: datetime | None = None,
        reconcile: bool = True,
    ) -> AnalyticsMaintenanceResult: ...
