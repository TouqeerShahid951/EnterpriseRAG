"""In-memory query analytics repository for tests and memory deployments."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from statistics import quantiles
from threading import RLock

from ..lineage_metadata import expired_lineage

from ..models import (
    AnalyticsExecutionRecord,
    AnalyticsExecutionRepository,
    AnalyticsBoundaryEvent,
    AnalyticsBucketSize,
    AnalyticsFilters,
    AnalyticsPage,
    AnalyticsRate,
    AnalyticsSummary,
    AnalyticsSeries,
    AnalyticsSeriesBucket,
    AnalyticsMaintenanceResult,
    AnalyticsDiagnostics,
    AnalyticsDocumentDiagnostics,
    AnalyticsDocumentUsage,
    AnalyticsCountStats,
    AnalyticsEvidenceUtilization,
    AnalyticsRankMovement,
    AnalyticsScoreStats,
    AnalyticsStageDiagnostics,
    AnalyticsTimingDiagnostics,
    AnalyticsTopKTurnover,
    AnalyticsQualityDiagnostics,
    AnalyticsClaimLedger,
    AnalyticsCohortObservation,
)


class InMemoryAnalyticsRepository(AnalyticsExecutionRepository):
    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, AnalyticsExecutionRecord] = {}
        self._boundary_events: dict[str, AnalyticsBoundaryEvent] = {}

    def record_boundary_event(self, event: AnalyticsBoundaryEvent) -> None:
        self._boundary_events.setdefault(event.event_id, event)

    def start_execution(self, record: AnalyticsExecutionRecord) -> AnalyticsExecutionRecord:
        with self._lock:
            existing = self._records.get(record.execution_id)
            if existing is not None:
                return existing
            record = replace(record, created_at=datetime.now(UTC))
            self._records[record.execution_id] = record
            return record

    def finish_execution(self, execution_id: str, **updates: object) -> AnalyticsExecutionRecord | None:
        with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return None
            if record.lifecycle == "terminal" and not (
                record.outcome == "interrupted" and record.reason_code == "analytics_heartbeat_expired"
                and record.last_heartbeat_at is not None
            ):
                return record
            for key in ("reason_code", "degraded_reason", "degraded"):
                updates.setdefault(key, None)
            finished = replace(record, lifecycle="terminal", **updates)
            self._records[execution_id] = finished
            return finished

    def heartbeat_execution(self, execution_id: str, *, grace_seconds: int) -> bool:
        with self._lock:
            if grace_seconds < 1:
                raise ValueError("grace_seconds must be positive")
            record = self._records.get(execution_id)
            if record is None or record.last_heartbeat_at is None:
                return False
            if record.lifecycle == "terminal" and not (
                record.outcome == "interrupted" and record.reason_code == "analytics_heartbeat_expired"
            ):
                return False
            now = datetime.now(UTC)
            self._records[execution_id] = replace(
                record, last_heartbeat_at=now, reconciliation_deadline_at=now + timedelta(seconds=grace_seconds),
                lifecycle="in_flight", finished_at=None, outcome=None,
                reason_code=None, degraded_reason=None, degraded=None,
            )
            return True

    def get_execution(self, execution_id: str) -> AnalyticsExecutionRecord | None:
        return self._records.get(execution_id)

    def list_executions(self, *, filters: AnalyticsFilters, limit: int, offset: int) -> AnalyticsPage:
        records = sorted(
            (record for record in self._records.values() if _matches(record, filters)),
            key=lambda record: (record.started_at, record.execution_id),
            reverse=True,
        )
        return AnalyticsPage(items=tuple(records[offset:offset + limit]), total=len(records))

    def summarize_executions(self, *, filters: AnalyticsFilters) -> AnalyticsSummary:
        records = [record for record in self._records.values() if _matches(record, filters)]
        terminal = [record for record in records if record.lifecycle == "terminal"]
        outcomes = {outcome: sum(record.outcome == outcome for record in terminal) for outcome in (
            "complete", "partial", "clarification", "abstained", "system_error", "access_denied", "cancelled", "interrupted", "artifact_submitted"
        )}
        answers = [record for record in terminal if record.work_kind == "answer"]
        latencies = sorted(record.latency_ms for record in answers if record.latency_ms is not None)
        applicable = [record for record in answers if record.verification_status not in (None, "skipped")]
        checked = [record for record in applicable if record.verification_status == "checked"]
        denominator = len(answers)
        return AnalyticsSummary(
            total_executions=len(records),
            terminal_executions=len(terminal),
            in_flight_executions=len(records) - len(terminal),
            complete=outcomes["complete"],
            partial=outcomes["partial"],
            clarification=outcomes["clarification"],
            abstained=outcomes["abstained"],
            system_error=outcomes["system_error"],
            access_denied=outcomes["access_denied"],
            cancelled=outcomes["cancelled"],
            interrupted=outcomes["interrupted"],
            artifact_submitted=outcomes["artifact_submitted"],
            answer_executions=denominator,
            unique_actor_count=len({record.actor_id for record in records}),
            verification_checked=len(checked),
            verification_applicable=len(applicable),
            p50_latency_ms=_percentile(latencies, 0.50),
            p95_latency_ms=_percentile(latencies, 0.95),
            complete_rate=AnalyticsRate(outcomes["complete"], denominator),
            abstention_rate=AnalyticsRate(outcomes["abstained"], denominator),
            system_error_rate=AnalyticsRate(outcomes["system_error"], denominator),
            verification_coverage=AnalyticsRate(len(checked), len(applicable)),
        )

    def series_executions(self, *, filters: AnalyticsFilters, bucket_size: AnalyticsBucketSize) -> AnalyticsSeries:
        records = [record for record in self._records.values() if _matches(record, filters)]
        cursor = _bucket_start(filters.created_from, bucket_size)
        buckets: list[AnalyticsSeriesBucket] = []
        while cursor < filters.created_to:
            ended_at = _bucket_end(cursor, bucket_size)
            bucket_records = [
                record for record in records if cursor <= record.started_at < ended_at
            ]
            buckets.append(_series_bucket(cursor, ended_at, bucket_records))
            cursor = ended_at
        return AnalyticsSeries(bucket_size=bucket_size, buckets=tuple(buckets))

    def diagnose_executions(self, *, filters: AnalyticsFilters) -> AnalyticsDiagnostics:
        records = [record for record in self._records.values() if _matches(record, filters)]
        status_counts: dict[str, int] = {}
        quality_status_counts: dict[str, int] = {}
        quality_method_counts: dict[str, int] = {}
        support_status_counts: dict[str, int] = {}
        quality_scores: list[float] = []
        quality_checked = quality_applicable = 0
        claim_ledger_executions = 0
        claim_ledger_counts = {key: 0 for key in (
            "applicable_claims", "supported_claims", "unsupported_claims",
            "unknown_claims", "cited_claims", "uncited_claims", "valid_quotes",
        )}
        cohort_values: dict[tuple[str, str, str | None], dict[str, object]] = {}
        document_usage: dict[str, dict[str, object]] = {}
        documents_per_query: list[float] = []
        overlaps: list[float] = []
        added_counts: list[float] = []
        dropped_counts: list[float] = []
        stage_values: dict[str, dict[str, object]] = {}
        timing_values: dict[str, dict[str, object]] = {}
        sent_source_count = cited_source_count = utilization_executions = 0
        rank_values: list[float] = []
        promoted = demoted = unchanged = 0
        for record in records:
            status = record.retrieval_lineage_status
            status_counts[status] = status_counts.get(status, 0) + 1
            if record.model_cohort and record.configuration_digest:
                cohort_key = (
                    record.model_cohort,
                    record.configuration_digest,
                    record.application_image_digest,
                )
                cohort = cohort_values.setdefault(
                    cohort_key,
                    {"count": 0, "first_observed_at": record.started_at},
                )
                cohort["count"] += 1
                cohort["first_observed_at"] = min(cohort["first_observed_at"], record.started_at)
            lineage = record.retrieval_lineage or {}
            retrieved_stage = _latest_stage(lineage, "retrieved")
            if retrieved_stage is not None:
                documents: dict[str, dict[str, object]] = {}
                for candidate in retrieved_stage.get("candidates") or []:
                    doc_id = candidate.get("doc_id")
                    if not doc_id:
                        continue
                    generation_id = candidate.get("index_generation_id")
                    key = f"{generation_id or ''}:{doc_id}"
                    document = documents.setdefault(
                        key,
                        {"doc_id": str(doc_id), "title": None, "generation_id": generation_id, "candidate_count": 0},
                    )
                    document["candidate_count"] += 1
                if documents:
                    documents_per_query.append(float(len(documents)))
                    for key, document in documents.items():
                        aggregate = document_usage.setdefault(
                            key,
                            {"doc_id": document["doc_id"], "title": document["title"], "generation_id": document["generation_id"], "executions": 0, "candidates": 0},
                        )
                        aggregate["executions"] += 1
                        aggregate["candidates"] += int(document["candidate_count"])
            input_stage = _latest_stage(lineage, "rerank_input")
            final_stage = _latest_stage(lineage, "final_evidence")
            if input_stage is not None and final_stage is not None:
                before = {candidate.get("candidate_key") for candidate in input_stage.get("candidates") or []}
                after = {candidate.get("candidate_key") for candidate in final_stage.get("candidates") or []}
                before.discard(None)
                after.discard(None)
                union = before | after
                if union:
                    overlaps.append(len(before & after) / len(union))
                    added_counts.append(float(len(after - before)))
                    dropped_counts.append(float(len(before - after)))
            if record.lifecycle == "terminal" and record.work_kind == "answer":
                quality_status = record.verification_status or "not_measured"
                quality_status_counts[quality_status] = quality_status_counts.get(quality_status, 0) + 1
                if quality_status != "skipped":
                    quality_applicable += 1
                if quality_status == "checked":
                    quality_checked += 1
                    _append_score(quality_scores, record.faithfulness_score)
                if record.verification_method:
                    quality_method_counts[record.verification_method] = quality_method_counts.get(record.verification_method, 0) + 1
                quality = lineage.get("quality") or {}
                for support_status, count in (quality.get("support_status_counts") or {}).items():
                    support_status_counts[str(support_status)] = support_status_counts.get(str(support_status), 0) + int(count or 0)
                ledger = quality.get("claim_ledger") or {}
                if ledger.get("status") == "captured":
                    claim_ledger_executions += 1
                    for key in claim_ledger_counts:
                        claim_ledger_counts[key] += int(ledger.get(key) or 0)
            generation = lineage.get("generation") or {}
            citation = lineage.get("citation") or {}
            if generation.get("status") == "available" and citation.get("status") == "available":
                utilization_executions += 1
                sent_source_count += int(generation.get("source_count") or 0)
                cited_source_count += int(citation.get("cited_source_count") or 0)
            inputs = {
                (stage.get("attempt"), candidate.get("candidate_key")): candidate
                for stage in lineage.get("stages", [])
                if stage.get("name") == "rerank_input" and not stage.get("truncated")
                for candidate in stage.get("candidates") or []
            }
            outputs = {
                (stage.get("attempt"), candidate.get("candidate_key")): candidate
                for stage in lineage.get("stages", [])
                if stage.get("name") == "reranked" and not stage.get("truncated")
                for candidate in stage.get("candidates") or []
            }
            for key in inputs.keys() & outputs.keys():
                before, after = int(inputs[key]["rank"]), int(outputs[key]["rank"])
                rank_values.append(float(abs(after - before)))
                if after < before:
                    promoted += 1
                elif after > before:
                    demoted += 1
                else:
                    unchanged += 1
            for stage in lineage.get("stages", []):
                name = str(stage.get("name") or "unknown")
                aggregate = stage_values.setdefault(
                    name,
                    {"executions": set(), "candidate_count": 0, "serialized": 0, "retrieval": [], "rerank": [], "adjusted": []},
                )
                aggregate["executions"].add(record.execution_id)
                aggregate["candidate_count"] += int(stage.get("candidate_count") or 0)
                aggregate["serialized"] += len(stage.get("candidates") or [])
                for candidate in stage.get("candidates") or []:
                    _append_score(aggregate["retrieval"], candidate.get("retrieval_score"))
                    _append_score(aggregate["rerank"], candidate.get("rerank_score"))
                    _append_score(aggregate["adjusted"], candidate.get("rerank_adjusted_score"))
            execution_timings: dict[str, list[float]] = {}
            for timing in (lineage.get("performance") or {}).get("node_timings", []):
                node = str(timing.get("node") or "unknown")
                _append_score(execution_timings.setdefault(node, []), timing.get("duration_ms"))
            for node, durations in execution_timings.items():
                aggregate = timing_values.setdefault(node, {"executions": set(), "durations": [], "samples": 0})
                aggregate["executions"].add(record.execution_id)
                aggregate["samples"] += len(durations)
                if durations:
                    aggregate["durations"].append(sum(durations))
        return AnalyticsDiagnostics(
            capture_status_counts=tuple(sorted(status_counts.items())),
            stages=tuple(
                AnalyticsStageDiagnostics(
                    name=name,
                    execution_count=len(values["executions"]),
                    candidate_count=int(values["candidate_count"]),
                    serialized_candidate_count=int(values["serialized"]),
                    retrieval_score=_score_stats(values["retrieval"]),
                    rerank_score=_score_stats(values["rerank"]),
                    adjusted_rerank_score=_score_stats(values["adjusted"]),
                )
                for name, values in sorted(stage_values.items())
            ),
            timings=tuple(
                AnalyticsTimingDiagnostics(
                    node=node,
                    execution_count=len(values["executions"]),
                    duration_count=values["samples"],
                    p50_ms=_percentile_float(values["durations"], 0.50),
                    p95_ms=_percentile_float(values["durations"], 0.95),
                )
                for node, values in sorted(timing_values.items())
            ),
            rank_movement=_rank_movement(
                rank_values, promoted=promoted, demoted=demoted, unchanged=unchanged
            ),
            evidence_utilization=AnalyticsEvidenceUtilization(
                status="available" if utilization_executions else "unavailable",
                execution_count=utilization_executions,
                sent_source_count=sent_source_count,
                cited_source_count=cited_source_count,
                utilization_rate=(
                    cited_source_count / sent_source_count
                    if sent_source_count
                    else None
                ),
            ),
            quality=AnalyticsQualityDiagnostics(
                status_counts=tuple(sorted(quality_status_counts.items())),
                method_counts=tuple(sorted(quality_method_counts.items())),
                support_status_counts=tuple(sorted(support_status_counts.items())),
                score=_score_stats(quality_scores),
                checked_count=quality_checked,
                applicable_count=quality_applicable,
                claim_ledger=AnalyticsClaimLedger(
                    status="available" if claim_ledger_executions else "unavailable",
                    execution_count=claim_ledger_executions,
                    applicable_claim_count=claim_ledger_counts["applicable_claims"],
                    supported_claim_count=claim_ledger_counts["supported_claims"],
                    unsupported_claim_count=claim_ledger_counts["unsupported_claims"],
                    unknown_claim_count=claim_ledger_counts["unknown_claims"],
                    cited_claim_count=claim_ledger_counts["cited_claims"],
                    uncited_claim_count=claim_ledger_counts["uncited_claims"],
                    valid_quote_count=claim_ledger_counts["valid_quotes"],
                    support_rate=AnalyticsRate(
                        claim_ledger_counts["supported_claims"],
                        claim_ledger_counts["applicable_claims"],
                    ),
                    citation_coverage=AnalyticsRate(
                        claim_ledger_counts["cited_claims"],
                        claim_ledger_counts["applicable_claims"],
                    ),
                ),
            ),
            documents=AnalyticsDocumentDiagnostics(
                status="available" if documents_per_query else "unavailable",
                documents_per_query=_count_stats(documents_per_query),
                top_documents=tuple(
                    AnalyticsDocumentUsage(
                        document_key=key,
                        document_title=values["title"],
                        generation_id=values["generation_id"],
                        execution_count=int(values["executions"]),
                        candidate_count=int(values["candidates"]),
                    )
                    for key, values in sorted(
                        document_usage.items(),
                        key=lambda item: (-int(item[1]["executions"]), -int(item[1]["candidates"]), item[0]),
                    )[:10]
                ),
                top_k_turnover=AnalyticsTopKTurnover(
                    status="available" if overlaps else "unavailable",
                    comparable_attempt_count=len(overlaps),
                    mean_overlap=_mean(overlaps),
                    p50_overlap=_percentile_float(overlaps, 0.50),
                    p95_overlap=_percentile_float(overlaps, 0.95),
                    mean_added=_mean(added_counts),
                    mean_dropped=_mean(dropped_counts),
                ),
            ),
            cohorts=tuple(
                AnalyticsCohortObservation(
                    model_cohort=model_cohort,
                    configuration_digest=configuration_digest,
                    application_image_digest=image_digest,
                    execution_count=int(values["count"]),
                    first_observed_at=values["first_observed_at"],
                )
                for (model_cohort, configuration_digest, image_digest), values in sorted(
                    cohort_values.items(), key=lambda item: item[1]["first_observed_at"]
                )
            ),
        )

    def maintain(
        self,
        *,
        as_of: datetime,
        retention_before: datetime,
        batch_size: int,
        lineage_before: datetime | None = None,
        reconcile: bool = True,
    ) -> AnalyticsMaintenanceResult:
        with self._lock:
            if batch_size < 1:
                raise ValueError("batch_size must be positive")
            lineage_before = lineage_before or as_of - timedelta(days=7)
            expired_lineages = 0
            for record in sorted(self._records.values(), key=lambda item: item.started_at):
                if expired_lineages >= batch_size:
                    break
                if (
                    record.lifecycle == "terminal"
                    and record.finished_at is not None
                    and record.finished_at < lineage_before
                    and record.retrieval_lineage is not None
                    and record.retrieval_lineage_status != "expired"
                ):
                    self._records[record.execution_id] = replace(
                        record, retrieval_lineage_status="expired",
                        retrieval_lineage=expired_lineage(record.retrieval_lineage),
                    )
                    expired_lineages += 1
            reconciled = 0
            for record in sorted(self._records.values(), key=lambda item: item.started_at):
                if not reconcile or reconciled >= batch_size:
                    break
                if (
                    record.lifecycle == "in_flight"
                    and record.last_heartbeat_at is not None
                    and record.reconciliation_deadline_at is not None
                    and record.reconciliation_deadline_at <= as_of
                ):
                    self._records[record.execution_id] = replace(
                        record,
                        lifecycle="terminal",
                        finished_at=as_of,
                        outcome="interrupted",
                        degraded=True,
                        reason_code="analytics_heartbeat_expired",
                        degraded_reason="analytics_heartbeat_expired",
                    )
                    reconciled += 1
            remaining = max(0, batch_size - reconciled)
            expired_ids = [
                record.execution_id
                for record in sorted(self._records.values(), key=lambda item: item.started_at)
                if remaining and record.lifecycle == "terminal" and record.started_at < retention_before
                and (record.reason_code != "analytics_heartbeat_expired" or record.finished_at < retention_before)
            ][:remaining]
            for execution_id in expired_ids:
                del self._records[execution_id]
            expired_boundary_ids = [
                event.event_id
                for event in sorted(self._boundary_events.values(), key=lambda item: item.occurred_at)
                if event.occurred_at < retention_before
            ][:batch_size]
            for event_id in expired_boundary_ids:
                del self._boundary_events[event_id]
            return AnalyticsMaintenanceResult(
                reconciled_execution_count=reconciled,
                deleted_execution_count=len(expired_ids),
                deleted_boundary_event_count=len(expired_boundary_ids),
                expired_lineage_count=expired_lineages,
            )

def _matches(record: AnalyticsExecutionRecord, filters: AnalyticsFilters) -> bool:
    if not filters.created_from <= record.started_at < filters.created_to:
        return False
    if filters.as_of is not None and (record.created_at or record.started_at) > filters.as_of:
        return False
    return all(
        value is None or getattr(record, field) == value
        for field, value in (
            ("origin", filters.origin),
            ("work_kind", filters.work_kind),
            ("actor_id", filters.actor_id),
            ("group_path", filters.group_path),
            ("outcome", filters.outcome),
            ("resolved_source_mode", filters.source_mode),
            ("final_intent", filters.intent),
            ("model_cohort", filters.model_cohort),
            ("configuration_digest", filters.configuration_digest),
        )
    )


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    return float(quantiles(values, n=100, method="inclusive")[int(percentile * 100) - 1])


def _append_score(values: list[float], value: object) -> None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        values.append(float(value))


def _score_stats(values: list[float]) -> AnalyticsScoreStats:
    return AnalyticsScoreStats(
        count=len(values),
        mean=sum(values) / len(values) if values else None,
        p50=_percentile_float(values, 0.50),
        p95=_percentile_float(values, 0.95),
        buckets=_score_buckets(values),
    )


def _rank_movement(
    values: list[float], *, promoted: int, demoted: int, unchanged: int
) -> AnalyticsRankMovement:
    return AnalyticsRankMovement(
        status="available" if values else "unavailable",
        count=len(values),
        mean_absolute=sum(values) / len(values) if values else None,
        p50_absolute=_percentile_float(values, 0.50),
        p95_absolute=_percentile_float(values, 0.95),
        promoted=promoted,
        demoted=demoted,
        unchanged=unchanged,
    )


def _percentile_float(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    return float(quantiles(values, n=100, method="inclusive")[int(percentile * 100) - 1])


def _score_buckets(values: list[float]) -> tuple[tuple[str, int], ...]:
    labels = ("0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0", "other")
    counts = dict.fromkeys(labels, 0)
    for value in values:
        if 0 <= value < 0.2:
            label = labels[0]
        elif value < 0.4:
            label = labels[1]
        elif value < 0.6:
            label = labels[2]
        elif value < 0.8:
            label = labels[3]
        elif value <= 1.0:
            label = labels[4]
        else:
            label = labels[5]
        counts[label] += 1
    return tuple((label, counts[label]) for label in labels)


def _bucket_start(value: datetime, bucket_size: AnalyticsBucketSize) -> datetime:
    value = value.astimezone(UTC)
    if bucket_size == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(minute=0, second=0, microsecond=0)


def _bucket_end(value: datetime, bucket_size: AnalyticsBucketSize) -> datetime:
    return value + (timedelta(days=1) if bucket_size == "day" else timedelta(hours=1))


def _series_bucket(
    started_at: datetime,
    ended_at: datetime,
    records: list[AnalyticsExecutionRecord],
) -> AnalyticsSeriesBucket:
    terminal = [record for record in records if record.lifecycle == "terminal"]
    answers = [record for record in terminal if record.work_kind == "answer"]
    outcomes = {
        outcome: sum(record.outcome == outcome for record in terminal)
        for outcome in (
            "complete", "partial", "clarification", "abstained", "system_error",
            "access_denied", "cancelled", "interrupted", "artifact_submitted",
        )
    }
    latencies = sorted(record.latency_ms for record in answers if record.latency_ms is not None)
    return AnalyticsSeriesBucket(
        started_at=started_at,
        ended_at=ended_at,
        total_executions=len(records),
        answer_executions=len(answers),
        complete=outcomes["complete"],
        partial=outcomes["partial"],
        clarification=outcomes["clarification"],
        abstained=outcomes["abstained"],
        system_error=outcomes["system_error"],
        access_denied=outcomes["access_denied"],
        cancelled=outcomes["cancelled"],
        interrupted=outcomes["interrupted"],
        artifact_submitted=outcomes["artifact_submitted"],
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        verification_checked=sum(record.verification_status == "checked" for record in answers),
        verification_applicable=sum(
            record.verification_status not in (None, "skipped") for record in answers
        ),
        faithfulness_score_mean=_mean(
            record.faithfulness_score
            for record in answers
            if record.verification_status == "checked"
        ),
    )


def _mean(values: object) -> float | None:
    numbers = [float(value) for value in values if isinstance(value, int | float)]
    return sum(numbers) / len(numbers) if numbers else None


def _count_stats(values: list[float]) -> AnalyticsCountStats:
    labels = ("1", "2", "3", "4", "5+")
    buckets = dict.fromkeys(labels, 0)
    for value in values:
        buckets[labels[min(max(int(value) - 1, 0), 4)]] += 1
    return AnalyticsCountStats(
        count=len(values),
        mean=_mean(values),
        p50=_percentile_float(values, 0.50),
        p95=_percentile_float(values, 0.95),
        buckets=tuple((label, buckets[label]) for label in labels),
    )


def _latest_stage(lineage: dict[str, object], name: str) -> dict[str, object] | None:
    stages = [
        stage
        for stage in lineage.get("stages", [])
        if stage.get("name") == name
        and stage.get("status") == "completed"
        and not stage.get("truncated")
    ]
    return max(stages, key=lambda stage: int(stage.get("attempt") or 0), default=None)
