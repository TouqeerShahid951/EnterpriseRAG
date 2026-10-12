"""HTTP contracts for query execution analytics."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from ...shared.contracts.http import ContractModel
from .lineage_metadata import lineage_metadata
from .models import (
    AnalyticsDiagnostics,
    AnalyticsClaimLedger,
    AnalyticsDocumentDiagnostics,
    AnalyticsEvidenceUtilization,
    AnalyticsExecutionRecord,
    AnalyticsRankMovement,
    AnalyticsQualityDiagnostics,
    AnalyticsScoreStats,
    AnalyticsSeries,
    AnalyticsStageDiagnostics,
    AnalyticsSummary,
    AnalyticsTimingDiagnostics,
)


class AnalyticsRateResponse(ContractModel):
    numerator: int = Field(..., ge=0)
    denominator: int = Field(..., ge=0)
    value: float | None = Field(default=None, ge=0, le=1)


class AnalyticsSummaryResponse(ContractModel):
    created_from: datetime
    created_to: datetime
    as_of: datetime
    total_executions: int = Field(..., ge=0)
    terminal_executions: int = Field(..., ge=0)
    in_flight_executions: int = Field(..., ge=0)
    complete: int = Field(..., ge=0)
    partial: int = Field(..., ge=0)
    clarification: int = Field(..., ge=0)
    abstained: int = Field(..., ge=0)
    system_error: int = Field(..., ge=0)
    access_denied: int = Field(..., ge=0)
    cancelled: int = Field(..., ge=0)
    interrupted: int = Field(..., ge=0)
    artifact_submitted: int = Field(..., ge=0)
    answer_executions: int = Field(..., ge=0)
    unique_actor_count: int = Field(..., ge=0)
    verification_checked: int = Field(..., ge=0)
    verification_applicable: int = Field(..., ge=0)
    p50_latency_ms: float | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    complete_rate: AnalyticsRateResponse
    abstention_rate: AnalyticsRateResponse
    system_error_rate: AnalyticsRateResponse
    verification_coverage: AnalyticsRateResponse
    timezone: Literal["UTC"] = "UTC"
    data_status: Literal["available", "empty"]


class AnalyticsExecutionResponse(ContractModel):
    execution_id: str
    trace_id: str
    session_id: str
    actor_id: str
    permission_version: int = Field(..., ge=0)
    origin: str
    work_kind: str
    group_path: str | None = None
    lifecycle: str
    started_at: datetime
    finished_at: datetime | None = None
    outcome: str | None = None
    answer_status: str | None = None
    reason_code: str | None = None
    last_heartbeat_at: datetime | None = None
    liveness_status: Literal["untracked", "active", "heartbeat_expired", "finished"] = "untracked"
    degraded: bool | None = None
    degraded_reason: str | None = None
    requested_source_mode: str | None = None
    resolved_source_mode: str | None = None
    initial_intent: str | None = None
    final_intent: str | None = None
    response_mode: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    verification_status: str | None = None
    verification_method: str | None = None
    faithfulness_score: float | None = Field(default=None, ge=0, le=1)
    retry_count: int = Field(..., ge=0)
    route_reroute_count: int = Field(..., ge=0)
    retrieved_hit_count: int | None = Field(default=None, ge=0)
    evidence_source_count: int | None = Field(default=None, ge=0)
    cited_source_count: int | None = Field(default=None, ge=0)
    max_retrieval_score: float | None = None
    max_rerank_score: float | None = None
    model_cohort: str | None = None
    configuration_digest: str | None = None
    application_image_digest: str | None = None
    cohort_snapshot: dict[str, object] | None = None
    retrieval_lineage_status: Literal[
        "not_captured", "available", "truncated", "unavailable", "expired"
    ] = "not_captured"
    retrieval_lineage: dict[str, object] | None = None
    review_reasons: list[str] = Field(default_factory=list)


class AnalyticsExecutionListResponse(ContractModel):
    items: list[AnalyticsExecutionResponse] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)
    offset: int = Field(..., ge=0)
    created_from: datetime
    created_to: datetime
    as_of: datetime
    timezone: Literal["UTC"] = "UTC"


class AnalyticsSeriesBucketResponse(ContractModel):
    started_at: datetime
    ended_at: datetime
    total_executions: int = Field(..., ge=0)
    answer_executions: int = Field(..., ge=0)
    complete: int = Field(..., ge=0)
    partial: int = Field(..., ge=0)
    clarification: int = Field(..., ge=0)
    abstained: int = Field(..., ge=0)
    system_error: int = Field(..., ge=0)
    access_denied: int = Field(..., ge=0)
    cancelled: int = Field(..., ge=0)
    interrupted: int = Field(..., ge=0)
    artifact_submitted: int = Field(..., ge=0)
    p50_latency_ms: float | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    verification_checked: int = Field(..., ge=0)
    verification_applicable: int = Field(..., ge=0)
    faithfulness_score_mean: float | None = Field(default=None, ge=0, le=1)


class AnalyticsSeriesResponse(ContractModel):
    bucket_size: Literal["hour", "day"]
    buckets: list[AnalyticsSeriesBucketResponse] = Field(default_factory=list)
    created_from: datetime
    created_to: datetime
    as_of: datetime
    timezone: Literal["UTC"] = "UTC"


class AnalyticsScoreStatsResponse(ContractModel):
    count: int = Field(..., ge=0)
    mean: float | None = None
    p50: float | None = None
    p95: float | None = None
    buckets: list[tuple[str, int]] = Field(default_factory=list)


class AnalyticsCountStatsResponse(ContractModel):
    count: int = Field(..., ge=0)
    mean: float | None = Field(default=None, ge=0)
    p50: float | None = Field(default=None, ge=0)
    p95: float | None = Field(default=None, ge=0)
    buckets: list[tuple[str, int]] = Field(default_factory=list)


class AnalyticsStageDiagnosticsResponse(ContractModel):
    name: str
    execution_count: int = Field(..., ge=0)
    candidate_count: int = Field(..., ge=0)
    serialized_candidate_count: int = Field(..., ge=0)
    retrieval_score: AnalyticsScoreStatsResponse
    rerank_score: AnalyticsScoreStatsResponse
    adjusted_rerank_score: AnalyticsScoreStatsResponse


class AnalyticsRankMovementResponse(ContractModel):
    status: Literal["available", "unavailable"]
    count: int = Field(..., ge=0)
    mean_absolute: float | None = Field(default=None, ge=0)
    p50_absolute: float | None = Field(default=None, ge=0)
    p95_absolute: float | None = Field(default=None, ge=0)
    promoted: int = Field(..., ge=0)
    demoted: int = Field(..., ge=0)
    unchanged: int = Field(..., ge=0)


class AnalyticsEvidenceUtilizationResponse(ContractModel):
    status: Literal["available", "unavailable"]
    execution_count: int = Field(..., ge=0)
    sent_source_count: int = Field(..., ge=0)
    cited_source_count: int = Field(..., ge=0)
    utilization_rate: float | None = Field(default=None, ge=0, le=1)


class AnalyticsTimingDiagnosticsResponse(ContractModel):
    node: str
    execution_count: int = Field(..., ge=0)
    duration_count: int = Field(..., ge=0)
    p50_ms: float | None = Field(default=None, ge=0)
    p95_ms: float | None = Field(default=None, ge=0)


class AnalyticsDiagnosticsResponse(ContractModel):
    capture_status_counts: dict[str, int] = Field(default_factory=dict)
    stages: list[AnalyticsStageDiagnosticsResponse] = Field(default_factory=list)
    timings: list[AnalyticsTimingDiagnosticsResponse] = Field(default_factory=list)
    rank_movement: AnalyticsRankMovementResponse
    evidence_utilization: AnalyticsEvidenceUtilizationResponse
    quality: "AnalyticsQualityDiagnosticsResponse"
    documents: "AnalyticsDocumentDiagnosticsResponse"
    cohorts: list["AnalyticsCohortObservationResponse"] = Field(default_factory=list)
    data_status: Literal["available", "empty"]


class AnalyticsQualityDiagnosticsResponse(ContractModel):
    status_counts: dict[str, int] = Field(default_factory=dict)
    method_counts: dict[str, int] = Field(default_factory=dict)
    support_status_counts: dict[str, int] = Field(default_factory=dict)
    score: AnalyticsScoreStatsResponse
    checked_count: int = Field(..., ge=0)
    applicable_count: int = Field(..., ge=0)
    claim_ledger: "AnalyticsClaimLedgerResponse"


class AnalyticsClaimLedgerResponse(ContractModel):
    status: Literal["available", "unavailable"]
    execution_count: int = Field(..., ge=0)
    applicable_claim_count: int = Field(..., ge=0)
    supported_claim_count: int = Field(..., ge=0)
    unsupported_claim_count: int = Field(..., ge=0)
    unknown_claim_count: int = Field(..., ge=0)
    cited_claim_count: int = Field(..., ge=0)
    uncited_claim_count: int = Field(..., ge=0)
    valid_quote_count: int = Field(..., ge=0)
    support_rate: AnalyticsRateResponse
    citation_coverage: AnalyticsRateResponse


class AnalyticsCohortObservationResponse(ContractModel):
    model_cohort: str
    configuration_digest: str
    application_image_digest: str | None = None
    execution_count: int = Field(..., ge=0)
    first_observed_at: datetime | None = None


class AnalyticsDocumentUsageResponse(ContractModel):
    document_key: str
    document_title: str | None = None
    generation_id: str | None = None
    execution_count: int = Field(..., ge=0)
    candidate_count: int = Field(..., ge=0)


class AnalyticsTopKTurnoverResponse(ContractModel):
    status: Literal["available", "unavailable"]
    comparable_attempt_count: int = Field(..., ge=0)
    mean_overlap: float | None = Field(default=None, ge=0, le=1)
    p50_overlap: float | None = Field(default=None, ge=0, le=1)
    p95_overlap: float | None = Field(default=None, ge=0, le=1)
    mean_added: float | None = Field(default=None, ge=0)
    mean_dropped: float | None = Field(default=None, ge=0)


class AnalyticsDocumentDiagnosticsResponse(ContractModel):
    status: Literal["available", "unavailable"]
    documents_per_query: AnalyticsCountStatsResponse
    top_documents: list[AnalyticsDocumentUsageResponse] = Field(default_factory=list)
    top_k_turnover: AnalyticsTopKTurnoverResponse


def summary_response(summary: AnalyticsSummary, *, created_from: datetime, created_to: datetime, as_of: datetime) -> AnalyticsSummaryResponse:
    return AnalyticsSummaryResponse(
        created_from=created_from,
        created_to=created_to,
        as_of=as_of,
        total_executions=summary.total_executions,
        terminal_executions=summary.terminal_executions,
        in_flight_executions=summary.in_flight_executions,
        complete=summary.complete,
        partial=summary.partial,
        clarification=summary.clarification,
        abstained=summary.abstained,
        system_error=summary.system_error,
        access_denied=summary.access_denied,
        cancelled=summary.cancelled,
        interrupted=summary.interrupted,
        artifact_submitted=summary.artifact_submitted,
        answer_executions=summary.answer_executions,
        unique_actor_count=summary.unique_actor_count,
        verification_checked=summary.verification_checked,
        verification_applicable=summary.verification_applicable,
        p50_latency_ms=summary.p50_latency_ms,
        p95_latency_ms=summary.p95_latency_ms,
        complete_rate=_rate(summary.complete_rate),
        abstention_rate=_rate(summary.abstention_rate),
        system_error_rate=_rate(summary.system_error_rate),
        verification_coverage=_rate(summary.verification_coverage),
        data_status="available" if summary.total_executions else "empty",
    )


def execution_response(record: AnalyticsExecutionRecord) -> AnalyticsExecutionResponse:
    return _execution_response(record, include_lineage=True)


def execution_list_response(record: AnalyticsExecutionRecord) -> AnalyticsExecutionResponse:
    return _execution_response(record, include_lineage=False)


def _execution_response(
    record: AnalyticsExecutionRecord, *, include_lineage: bool
) -> AnalyticsExecutionResponse:
    values = asdict(record)
    values.pop("created_at", None)
    values.pop("reconciliation_deadline_at", None)
    if record.reason_code == "analytics_heartbeat_expired" and record.outcome == "interrupted":
        values["liveness_status"] = "heartbeat_expired"
    elif record.lifecycle == "terminal":
        values["liveness_status"] = "finished"
    elif record.last_heartbeat_at is None:
        values["liveness_status"] = "untracked"
    elif record.reconciliation_deadline_at is not None and record.reconciliation_deadline_at <= datetime.now(UTC):
        values["liveness_status"] = "heartbeat_expired"
    else:
        values["liveness_status"] = "active"
    values["retrieval_lineage"] = lineage_metadata(record.retrieval_lineage) if include_lineage else None
    values["review_reasons"] = review_reasons_for(record)
    return AnalyticsExecutionResponse.model_validate(values)


def series_response(series: AnalyticsSeries, *, created_from: datetime, created_to: datetime, as_of: datetime) -> AnalyticsSeriesResponse:
    return AnalyticsSeriesResponse(
        bucket_size=series.bucket_size,
        buckets=[AnalyticsSeriesBucketResponse.model_validate(asdict(bucket)) for bucket in series.buckets],
        created_from=created_from,
        created_to=created_to,
        as_of=as_of,
    )


def diagnostics_response(diagnostics: AnalyticsDiagnostics) -> AnalyticsDiagnosticsResponse:
    return AnalyticsDiagnosticsResponse(
        capture_status_counts=dict(diagnostics.capture_status_counts),
        stages=[_stage_diagnostics_response(stage) for stage in diagnostics.stages],
        timings=[_timing_diagnostics_response(timing) for timing in diagnostics.timings],
        rank_movement=_rank_movement_response(diagnostics.rank_movement),
        evidence_utilization=_evidence_utilization_response(diagnostics.evidence_utilization),
        quality=_quality_diagnostics_response(diagnostics.quality),
        documents=_document_diagnostics_response(diagnostics.documents),
        cohorts=[
            AnalyticsCohortObservationResponse.model_validate(asdict(cohort))
            for cohort in diagnostics.cohorts
        ],
        data_status="available" if diagnostics.capture_status_counts else "empty",
    )


def _quality_diagnostics_response(
    quality: AnalyticsQualityDiagnostics,
) -> AnalyticsQualityDiagnosticsResponse:
    return AnalyticsQualityDiagnosticsResponse(
        status_counts=dict(quality.status_counts),
        method_counts=dict(quality.method_counts),
        support_status_counts=dict(quality.support_status_counts),
        score=_score_stats_response(quality.score),
        checked_count=quality.checked_count,
        applicable_count=quality.applicable_count,
        claim_ledger=_claim_ledger_response(quality.claim_ledger),
    )


def _claim_ledger_response(ledger: AnalyticsClaimLedger) -> AnalyticsClaimLedgerResponse:
    return AnalyticsClaimLedgerResponse(
        status=ledger.status,
        execution_count=ledger.execution_count,
        applicable_claim_count=ledger.applicable_claim_count,
        supported_claim_count=ledger.supported_claim_count,
        unsupported_claim_count=ledger.unsupported_claim_count,
        unknown_claim_count=ledger.unknown_claim_count,
        cited_claim_count=ledger.cited_claim_count,
        uncited_claim_count=ledger.uncited_claim_count,
        valid_quote_count=ledger.valid_quote_count,
        support_rate=_rate(ledger.support_rate),
        citation_coverage=_rate(ledger.citation_coverage),
    )


def _document_diagnostics_response(
    documents: AnalyticsDocumentDiagnostics,
) -> AnalyticsDocumentDiagnosticsResponse:
    return AnalyticsDocumentDiagnosticsResponse(
        status=documents.status,
        documents_per_query=AnalyticsCountStatsResponse(
            count=documents.documents_per_query.count,
            mean=documents.documents_per_query.mean,
            p50=documents.documents_per_query.p50,
            p95=documents.documents_per_query.p95,
            buckets=list(documents.documents_per_query.buckets),
        ),
        top_documents=[
            AnalyticsDocumentUsageResponse.model_validate({**asdict(document), "document_title": None})
            for document in documents.top_documents
        ],
        top_k_turnover=AnalyticsTopKTurnoverResponse.model_validate(
            asdict(documents.top_k_turnover)
        ),
    )


def _stage_diagnostics_response(stage: AnalyticsStageDiagnostics) -> AnalyticsStageDiagnosticsResponse:
    return AnalyticsStageDiagnosticsResponse(
        name=stage.name,
        execution_count=stage.execution_count,
        candidate_count=stage.candidate_count,
        serialized_candidate_count=stage.serialized_candidate_count,
        retrieval_score=_score_stats_response(stage.retrieval_score),
        rerank_score=_score_stats_response(stage.rerank_score),
        adjusted_rerank_score=_score_stats_response(stage.adjusted_rerank_score),
    )


def _score_stats_response(stats: AnalyticsScoreStats) -> AnalyticsScoreStatsResponse:
    return AnalyticsScoreStatsResponse(
        count=stats.count,
        mean=stats.mean,
        p50=stats.p50,
        p95=stats.p95,
        buckets=list(stats.buckets),
    )


def _rank_movement_response(movement: AnalyticsRankMovement) -> AnalyticsRankMovementResponse:
    return AnalyticsRankMovementResponse.model_validate(asdict(movement))


def _evidence_utilization_response(
    utilization: AnalyticsEvidenceUtilization,
) -> AnalyticsEvidenceUtilizationResponse:
    return AnalyticsEvidenceUtilizationResponse.model_validate(asdict(utilization))


def _timing_diagnostics_response(timing: AnalyticsTimingDiagnostics) -> AnalyticsTimingDiagnosticsResponse:
    return AnalyticsTimingDiagnosticsResponse(
        node=timing.node,
        execution_count=timing.execution_count,
        duration_count=timing.duration_count,
        p50_ms=timing.p50_ms,
        p95_ms=timing.p95_ms,
    )


def _rate(rate) -> AnalyticsRateResponse:
    return AnalyticsRateResponse(
        numerator=rate.numerator,
        denominator=rate.denominator,
        value=rate.value,
    )


def review_reasons_for(record: AnalyticsExecutionRecord) -> list[str]:
    reasons: list[str] = []
    if record.outcome == "partial":
        reasons.append("partial_answer")
    if record.outcome == "system_error":
        reasons.append("system_error")
    if record.verification_status == "failed":
        reasons.append("failed_verification")
    if record.degraded:
        reasons.append("degraded_execution")
    if (
        record.work_kind == "answer"
        and record.outcome in {"complete", "partial"}
        and record.evidence_source_count is not None
        and record.evidence_source_count > 0
        and record.cited_source_count == 0
    ):
        reasons.append("missing_citation")
    return reasons
