"""PostgreSQL query analytics repository."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import json
from typing import Any

from ....shared.persistence import PostgresConnectionMixin
from ..models import (
    AnalyticsExecutionRecord,
    AnalyticsExecutionRepository,
    AnalyticsBucketSize,
    AnalyticsBoundaryEvent,
    AnalyticsFilters,
    AnalyticsMaintenanceResult,
    AnalyticsPage,
    AnalyticsRate,
    AnalyticsSummary,
    AnalyticsSeries,
    AnalyticsSeriesBucket,
    AnalyticsDiagnostics,
    AnalyticsDocumentDiagnostics,
    AnalyticsDocumentUsage,
    AnalyticsCountStats,
    AnalyticsEvidenceUtilization,
    AnalyticsRankMovement,
    AnalyticsQualityDiagnostics,
    AnalyticsScoreStats,
    AnalyticsStageDiagnostics,
    AnalyticsTimingDiagnostics,
    AnalyticsTopKTurnover,
    AnalyticsCohortObservation,
    AnalyticsClaimLedger,
)


class PostgresAnalyticsRepository(PostgresConnectionMixin, AnalyticsExecutionRepository):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def record_boundary_event(self, event: AnalyticsBoundaryEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO query_analytics_boundary_events (
                    event_id, occurred_at, route_path, status_code, reason_code, actor_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (event.event_id, event.occurred_at, event.route_path, event.status_code, event.reason_code, event.actor_id),
            )

    def start_execution(self, record: AnalyticsExecutionRecord) -> AnalyticsExecutionRecord:
        row = asdict(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO query_analytics_executions (
                    execution_id, trace_id, session_id, actor_id, permission_version,
                    origin, work_kind, group_path, requested_source_mode, lifecycle, started_at,
                    model_cohort, configuration_digest, application_image_digest, cohort_snapshot,
                    reconciliation_deadline_at, last_heartbeat_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'in_flight', %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (execution_id) DO NOTHING
                """,
                tuple(
                    json.dumps(row[key]) if key == "cohort_snapshot" and row[key] is not None else row[key]
                    for key in (
                        "execution_id", "trace_id", "session_id", "actor_id",
                        "permission_version", "origin", "work_kind", "group_path", "requested_source_mode", "started_at",
                        "model_cohort", "configuration_digest", "application_image_digest", "cohort_snapshot",
                        "reconciliation_deadline_at", "last_heartbeat_at",
                    )
                ),
            )
        return self.get_execution(record.execution_id) or record

    def finish_execution(self, execution_id: str, **updates: object) -> AnalyticsExecutionRecord | None:
        allowed = {
            "finished_at", "outcome", "answer_status", "reason_code", "degraded", "degraded_reason",
            "resolved_source_mode", "initial_intent", "final_intent", "response_mode",
            "latency_ms", "verification_status", "verification_method", "faithfulness_score",
            "retry_count", "route_reroute_count", "retrieved_hit_count", "evidence_source_count",
            "cited_source_count", "max_retrieval_score", "max_rerank_score",
            "retrieval_lineage_status", "retrieval_lineage",
        }
        values = {key: value for key, value in updates.items() if key in allowed}
        if not values:
            return self.get_execution(execution_id)
        # A real terminal result supersedes only an inferred heartbeat interruption.
        for key in ("reason_code", "degraded_reason", "degraded"):
            values.setdefault(key, None)
        assignments = ", ".join(
            f"{key} = %s::jsonb" if key == "retrieval_lineage" else f"{key} = %s"
            for key in values
        )
        params = tuple(
            json.dumps(value) if key == "retrieval_lineage" and value is not None else value
            for key, value in values.items()
        ) + (execution_id,)
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE query_analytics_executions
                SET lifecycle = 'terminal', {assignments}
                WHERE execution_id = %s AND (
                    lifecycle = 'in_flight' OR (
                        outcome = 'interrupted' AND reason_code = 'analytics_heartbeat_expired'
                        AND last_heartbeat_at IS NOT NULL
                    )
                )
                """,
                params,
            )
        return self.get_execution(execution_id)

    def heartbeat_execution(self, execution_id: str, *, grace_seconds: int) -> bool:
        if grace_seconds < 1:
            raise ValueError("grace_seconds must be positive")
        with self._connect() as conn:
            conn.execute("SET LOCAL statement_timeout = '2s'")
            conn.execute("SET LOCAL lock_timeout = '1s'")
            row = conn.execute(
                """
                UPDATE query_analytics_executions
                SET last_heartbeat_at = statement_timestamp(),
                    reconciliation_deadline_at = statement_timestamp() + %s * INTERVAL '1 second',
                    lifecycle = 'in_flight', finished_at = NULL, outcome = NULL,
                    reason_code = NULL, degraded_reason = NULL, degraded = NULL
                WHERE execution_id = %s AND last_heartbeat_at IS NOT NULL AND (
                    lifecycle = 'in_flight' OR (
                        outcome = 'interrupted' AND reason_code = 'analytics_heartbeat_expired'
                    )
                )
                RETURNING execution_id
                """,
                (grace_seconds, execution_id),
            ).fetchone()
        return row is not None

    def get_execution(self, execution_id: str) -> AnalyticsExecutionRecord | None:
        row = self._execute_optional(
            "SELECT * FROM query_analytics_executions WHERE execution_id = %s",
            (execution_id,),
        )
        return _record_from_row(row) if row else None

    def list_executions(self, *, filters: AnalyticsFilters, limit: int, offset: int) -> AnalyticsPage:
        where, params = _where(filters)
        rows = self._execute_all(
            f"""
            SELECT *, COUNT(*) OVER()::int AS total_count
            FROM query_analytics_executions
            WHERE {where}
            ORDER BY started_at DESC, execution_id DESC
            LIMIT %s OFFSET %s
            """,
            params + (limit, offset),
        )
        total = int(rows[0]["total_count"]) if rows else self._count(filters)
        return AnalyticsPage(items=tuple(_record_from_row(row) for row in rows), total=total)

    def summarize_executions(self, *, filters: AnalyticsFilters) -> AnalyticsSummary:
        where, params = _where(filters)
        row = self._execute_one(
            f"""
            SELECT
                COUNT(*)::int AS total_executions,
                COUNT(*) FILTER (WHERE lifecycle = 'terminal')::int AS terminal_executions,
                COUNT(*) FILTER (WHERE lifecycle = 'in_flight')::int AS in_flight_executions,
                COUNT(*) FILTER (WHERE outcome = 'complete')::int AS complete,
                COUNT(*) FILTER (WHERE outcome = 'partial')::int AS partial,
                COUNT(*) FILTER (WHERE outcome = 'clarification')::int AS clarification,
                COUNT(*) FILTER (WHERE outcome = 'abstained')::int AS abstained,
                COUNT(*) FILTER (WHERE outcome = 'system_error')::int AS system_error,
                COUNT(*) FILTER (WHERE outcome = 'access_denied')::int AS access_denied,
                COUNT(*) FILTER (WHERE outcome = 'cancelled')::int AS cancelled,
                COUNT(*) FILTER (WHERE outcome = 'interrupted')::int AS interrupted,
                COUNT(*) FILTER (WHERE outcome = 'artifact_submitted')::int AS artifact_submitted,
                COUNT(*) FILTER (WHERE lifecycle = 'terminal' AND work_kind = 'answer')::int AS answer_executions,
                COUNT(DISTINCT actor_id)::int AS unique_actor_count,
                COUNT(*) FILTER (WHERE lifecycle = 'terminal' AND work_kind = 'answer' AND verification_status = 'checked')::int AS verification_checked,
                COUNT(*) FILTER (WHERE lifecycle = 'terminal' AND work_kind = 'answer' AND verification_status IS NOT NULL AND verification_status <> 'skipped')::int AS verification_applicable,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE lifecycle = 'terminal' AND work_kind = 'answer' AND latency_ms IS NOT NULL)::float8 AS p50_latency_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE lifecycle = 'terminal' AND work_kind = 'answer' AND latency_ms IS NOT NULL)::float8 AS p95_latency_ms
            FROM query_analytics_executions
            WHERE {where}
            """,
            params,
        )
        denominator = int(row["answer_executions"])
        applicable = int(row["verification_applicable"])
        return AnalyticsSummary(
            total_executions=int(row["total_executions"]),
            terminal_executions=int(row["terminal_executions"]),
            in_flight_executions=int(row["in_flight_executions"]),
            complete=int(row["complete"]),
            partial=int(row["partial"]),
            clarification=int(row["clarification"]),
            abstained=int(row["abstained"]),
            system_error=int(row["system_error"]),
            access_denied=int(row["access_denied"]),
            cancelled=int(row["cancelled"]),
            interrupted=int(row["interrupted"]),
            artifact_submitted=int(row["artifact_submitted"]),
            answer_executions=denominator,
            unique_actor_count=int(row["unique_actor_count"]),
            verification_checked=int(row["verification_checked"]),
            verification_applicable=applicable,
            p50_latency_ms=row["p50_latency_ms"],
            p95_latency_ms=row["p95_latency_ms"],
            complete_rate=AnalyticsRate(int(row["complete"]), denominator),
            abstention_rate=AnalyticsRate(int(row["abstained"]), denominator),
            system_error_rate=AnalyticsRate(int(row["system_error"]), denominator),
            verification_coverage=AnalyticsRate(int(row["verification_checked"]), applicable),
        )

    def series_executions(self, *, filters: AnalyticsFilters, bucket_size: AnalyticsBucketSize) -> AnalyticsSeries:
        unit = bucket_size
        step = f"1 {bucket_size}"
        where, filter_params = _where(filters, alias="e")
        rows = self._execute_all(
            f"""
            WITH buckets AS (
                SELECT bucket_start, bucket_start + %s::interval AS bucket_end
                FROM generate_series(
                    date_trunc(%s, %s::timestamptz),
                    date_trunc(%s, (%s::timestamptz - interval '1 microsecond')),
                    %s::interval
                ) AS series(bucket_start)
            )
            SELECT
                b.bucket_start,
                b.bucket_end,
                COUNT(e.execution_id)::int AS total_executions,
                COUNT(e.execution_id) FILTER (WHERE e.lifecycle = 'terminal' AND e.work_kind = 'answer')::int AS answer_executions,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'complete')::int AS complete,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'partial')::int AS partial,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'clarification')::int AS clarification,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'abstained')::int AS abstained,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'system_error')::int AS system_error,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'access_denied')::int AS access_denied,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'cancelled')::int AS cancelled,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'interrupted')::int AS interrupted,
                COUNT(e.execution_id) FILTER (WHERE e.outcome = 'artifact_submitted')::int AS artifact_submitted,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY e.latency_ms)
                    FILTER (WHERE e.lifecycle = 'terminal' AND e.work_kind = 'answer' AND e.latency_ms IS NOT NULL)::float8 AS p50_latency_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY e.latency_ms)
                    FILTER (WHERE e.lifecycle = 'terminal' AND e.work_kind = 'answer' AND e.latency_ms IS NOT NULL)::float8 AS p95_latency_ms,
                COUNT(e.execution_id) FILTER (WHERE e.lifecycle = 'terminal' AND e.work_kind = 'answer' AND e.verification_status = 'checked')::int AS verification_checked,
                COUNT(e.execution_id) FILTER (WHERE e.lifecycle = 'terminal' AND e.work_kind = 'answer' AND e.verification_status IS NOT NULL AND e.verification_status <> 'skipped')::int AS verification_applicable,
                AVG(e.faithfulness_score) FILTER (WHERE e.lifecycle = 'terminal' AND e.work_kind = 'answer' AND e.verification_status = 'checked' AND e.faithfulness_score IS NOT NULL)::float8 AS faithfulness_score_mean
            FROM buckets b
            LEFT JOIN query_analytics_executions e
                ON e.started_at >= b.bucket_start
                AND e.started_at < b.bucket_end
                AND {where}
            GROUP BY b.bucket_start, b.bucket_end
            ORDER BY b.bucket_start
            """,
            (step, unit, filters.created_from, unit, filters.created_to, step) + filter_params,
        )
        return AnalyticsSeries(
            bucket_size=bucket_size,
            buckets=tuple(
                AnalyticsSeriesBucket(
                    started_at=row["bucket_start"],
                    ended_at=row["bucket_end"],
                    total_executions=int(row["total_executions"]),
                    answer_executions=int(row["answer_executions"]),
                    complete=int(row["complete"]),
                    partial=int(row["partial"]),
                    clarification=int(row["clarification"]),
                    abstained=int(row["abstained"]),
                    system_error=int(row["system_error"]),
                    access_denied=int(row["access_denied"]),
                    cancelled=int(row["cancelled"]),
                    interrupted=int(row["interrupted"]),
                    artifact_submitted=int(row["artifact_submitted"]),
                    p50_latency_ms=row["p50_latency_ms"],
                    p95_latency_ms=row["p95_latency_ms"],
                    verification_checked=int(row["verification_checked"]),
                    verification_applicable=int(row["verification_applicable"]),
                    faithfulness_score_mean=row["faithfulness_score_mean"],
                )
                for row in rows
            ),
        )

    def diagnose_executions(self, *, filters: AnalyticsFilters) -> AnalyticsDiagnostics:
        where, params = _where(filters, alias="e")
        status_rows = self._execute_all(
            f"""
            SELECT e.retrieval_lineage_status AS status, COUNT(*)::int AS count
            FROM query_analytics_executions e
            WHERE {where}
            GROUP BY e.retrieval_lineage_status
            ORDER BY e.retrieval_lineage_status
            """,
            params,
        )
        quality_status_rows = self._execute_all(
            f"""
            SELECT COALESCE(e.verification_status, 'not_measured') AS status, COUNT(*)::int AS count
            FROM query_analytics_executions e
            WHERE {where} AND e.lifecycle = 'terminal' AND e.work_kind = 'answer'
            GROUP BY COALESCE(e.verification_status, 'not_measured')
            ORDER BY status
            """,
            params,
        )
        quality_method_rows = self._execute_all(
            f"""
            SELECT e.verification_method AS method, COUNT(*)::int AS count
            FROM query_analytics_executions e
            WHERE {where} AND e.lifecycle = 'terminal' AND e.work_kind = 'answer'
              AND e.verification_method IS NOT NULL
            GROUP BY e.verification_method
            ORDER BY e.verification_method
            """,
            params,
        )
        quality_score_row = self._execute_one(
            f"""
            SELECT
                COUNT(e.faithfulness_score)::int AS faithfulness_count,
                AVG(e.faithfulness_score)::float8 AS faithfulness_mean,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY e.faithfulness_score)::float8 AS faithfulness_p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY e.faithfulness_score)::float8 AS faithfulness_p95,
                {_score_bucket_select('e.faithfulness_score', 'faithfulness')}
            FROM query_analytics_executions e
            WHERE {where} AND e.lifecycle = 'terminal' AND e.work_kind = 'answer'
              AND e.verification_status = 'checked' AND e.faithfulness_score IS NOT NULL
            """,
            params,
        )
        claim_ledger_row = self._execute_one(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE ledger->>'status' = 'captured')::int AS execution_count,
                COALESCE(SUM((ledger->>'applicable_claims')::int) FILTER (WHERE ledger->>'status' = 'captured'), 0)::int AS applicable_claim_count,
                COALESCE(SUM((ledger->>'supported_claims')::int) FILTER (WHERE ledger->>'status' = 'captured'), 0)::int AS supported_claim_count,
                COALESCE(SUM((ledger->>'unsupported_claims')::int) FILTER (WHERE ledger->>'status' = 'captured'), 0)::int AS unsupported_claim_count,
                COALESCE(SUM((ledger->>'unknown_claims')::int) FILTER (WHERE ledger->>'status' = 'captured'), 0)::int AS unknown_claim_count,
                COALESCE(SUM((ledger->>'cited_claims')::int) FILTER (WHERE ledger->>'status' = 'captured'), 0)::int AS cited_claim_count,
                COALESCE(SUM((ledger->>'uncited_claims')::int) FILTER (WHERE ledger->>'status' = 'captured'), 0)::int AS uncited_claim_count,
                COALESCE(SUM((ledger->>'valid_quotes')::int) FILTER (WHERE ledger->>'status' = 'captured'), 0)::int AS valid_quote_count
            FROM query_analytics_executions e
            LEFT JOIN LATERAL (
                SELECT e.retrieval_lineage->'quality'->'claim_ledger' AS ledger
            ) AS claim ON TRUE
            WHERE {where} AND e.lifecycle = 'terminal' AND e.work_kind = 'answer'
            """,
            params,
        )
        cohort_rows = self._execute_all(
            f"""
            SELECT model_cohort, configuration_digest, application_image_digest,
                   COUNT(*)::int AS execution_count, MIN(started_at) AS first_observed_at
            FROM query_analytics_executions e
            WHERE {where}
              AND model_cohort IS NOT NULL AND configuration_digest IS NOT NULL
            GROUP BY model_cohort, configuration_digest, application_image_digest
            ORDER BY first_observed_at, model_cohort, configuration_digest
            LIMIT 20
            """,
            params,
        )
        document_rows = self._execute_all(
            f"""
            WITH filtered AS (
                SELECT e.execution_id, e.retrieval_lineage
                FROM query_analytics_executions e
                WHERE {where} AND e.retrieval_lineage IS NOT NULL
            ), retrieved AS (
                SELECT DISTINCT ON (f.execution_id)
                    f.execution_id, s.stage
                FROM filtered f
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(f.retrieval_lineage->'stages', '[]'::jsonb)
                ) AS s(stage)
                WHERE s.stage->>'name' = 'retrieved'
                  AND s.stage->>'status' = 'completed'
                  AND COALESCE((s.stage->>'truncated')::bool, FALSE) = FALSE
                ORDER BY f.execution_id, (s.stage->>'attempt')::int DESC
            ), documents_per_execution AS (
                SELECT
                    execution_id,
                    COALESCE(NULLIF(candidate->>'index_generation_id', ''), '') || ':' || (candidate->>'doc_id') AS document_key,
                    NULL::text AS document_title,
                    NULLIF(MAX(candidate->>'index_generation_id'), '') AS generation_id,
                    COUNT(*)::int AS candidate_count
                FROM retrieved
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(retrieved.stage->'candidates', '[]'::jsonb)
                ) AS c(candidate)
                WHERE candidate->>'doc_id' IS NOT NULL
                GROUP BY execution_id, document_key
            )
            SELECT document_key, MAX(document_title) AS document_title, MAX(generation_id) AS generation_id,
                   COUNT(*)::int AS execution_count, SUM(candidate_count)::int AS candidate_count
            FROM documents_per_execution
            GROUP BY document_key
            ORDER BY execution_count DESC, candidate_count DESC, document_key
            LIMIT 10
            """,
            params,
        )
        documents_per_query_row = self._execute_one(
            f"""
            WITH filtered AS (
                SELECT e.execution_id, e.retrieval_lineage
                FROM query_analytics_executions e
                WHERE {where} AND e.retrieval_lineage IS NOT NULL
            ), retrieved AS (
                SELECT DISTINCT ON (f.execution_id)
                    f.execution_id, s.stage
                FROM filtered f
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(f.retrieval_lineage->'stages', '[]'::jsonb)
                ) AS s(stage)
                WHERE s.stage->>'name' = 'retrieved'
                  AND s.stage->>'status' = 'completed'
                  AND COALESCE((s.stage->>'truncated')::bool, FALSE) = FALSE
                ORDER BY f.execution_id, (s.stage->>'attempt')::int DESC
            ), counts AS (
                SELECT retrieved.execution_id, COUNT(DISTINCT
                    COALESCE(NULLIF(candidate->>'index_generation_id', ''), '') || ':' || (candidate->>'doc_id')
                )::float8 AS documents
                FROM retrieved
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(retrieved.stage->'candidates', '[]'::jsonb)
                ) AS c(candidate)
                WHERE candidate->>'doc_id' IS NOT NULL
                GROUP BY retrieved.execution_id
            )
            SELECT COUNT(*)::int AS count, AVG(documents)::float8 AS mean,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY documents)::float8 AS p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY documents)::float8 AS p95,
                   {_count_bucket_select('documents')}
            FROM counts
            """,
            params,
        )
        turnover_row = self._execute_one(
            f"""
            WITH filtered AS (
                SELECT e.execution_id, e.retrieval_lineage
                FROM query_analytics_executions e
                WHERE {where} AND e.retrieval_lineage IS NOT NULL
            ), candidates AS (
                SELECT f.execution_id, (stage->>'attempt')::int AS attempt,
                       stage->>'name' AS name, candidate->>'candidate_key' AS candidate_key
                FROM filtered f
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(f.retrieval_lineage->'stages', '[]'::jsonb)
                ) AS s(stage)
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(stage->'candidates', '[]'::jsonb)
                ) AS c(candidate)
                WHERE stage->>'status' = 'completed'
                  AND COALESCE((stage->>'truncated')::bool, FALSE) = FALSE
                  AND candidate->>'candidate_key' IS NOT NULL
            ), inputs AS (
                SELECT DISTINCT execution_id, attempt, candidate_key
                FROM candidates WHERE name = 'rerank_input'
            ), finals AS (
                SELECT DISTINCT execution_id, attempt, candidate_key
                FROM candidates WHERE name = 'final_evidence'
            ), comparisons AS (
                SELECT COALESCE(i.execution_id, f.execution_id) AS execution_id,
                       COALESCE(i.attempt, f.attempt) AS attempt,
                       COUNT(i.candidate_key)::int AS input_count,
                       COUNT(f.candidate_key)::int AS final_count,
                       COUNT(*) FILTER (WHERE i.candidate_key IS NOT NULL AND f.candidate_key IS NOT NULL)::int AS overlap_count,
                       COUNT(*) FILTER (WHERE i.candidate_key IS NULL)::int AS added_count,
                       COUNT(*) FILTER (WHERE f.candidate_key IS NULL)::int AS dropped_count
                FROM inputs i
                FULL OUTER JOIN finals f USING (execution_id, attempt, candidate_key)
                GROUP BY COALESCE(i.execution_id, f.execution_id), COALESCE(i.attempt, f.attempt)
                HAVING COUNT(i.candidate_key) > 0 AND COUNT(f.candidate_key) > 0
            )
            SELECT COUNT(*)::int AS comparable_attempt_count,
                   AVG(overlap_count::float8 / NULLIF(input_count + final_count - overlap_count, 0))::float8 AS mean_overlap,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY overlap_count::float8 / NULLIF(input_count + final_count - overlap_count, 0))::float8 AS p50_overlap,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY overlap_count::float8 / NULLIF(input_count + final_count - overlap_count, 0))::float8 AS p95_overlap,
                   AVG(added_count)::float8 AS mean_added,
                   AVG(dropped_count)::float8 AS mean_dropped
            FROM comparisons
            """,
            params,
        )
        support_rows = self._execute_all(
            f"""
            SELECT support.key AS support_status, SUM((support.value)::int)::int AS count
            FROM query_analytics_executions e
            CROSS JOIN LATERAL jsonb_each_text(
                COALESCE(e.retrieval_lineage->'quality'->'support_status_counts', '{{}}'::jsonb)
            ) AS support(key, value)
            WHERE {where} AND e.retrieval_lineage IS NOT NULL
            GROUP BY support.key
            ORDER BY support.key
            """,
            params,
        )
        stage_rows = self._execute_all(
            f"""
            WITH filtered AS (
                SELECT e.execution_id, e.retrieval_lineage
                FROM query_analytics_executions e
                WHERE {where} AND e.retrieval_lineage IS NOT NULL
            ), stages AS (
                SELECT f.execution_id, jsonb_array_elements(
                    COALESCE(f.retrieval_lineage->'stages', '[]'::jsonb)
                ) AS stage
                FROM filtered f
            )
            SELECT
                stage->>'name' AS name,
                COUNT(DISTINCT execution_id)::int AS execution_count,
                COALESCE(SUM((stage->>'candidate_count')::int), 0)::int AS candidate_count,
                COALESCE(SUM(jsonb_array_length(COALESCE(stage->'candidates', '[]'::jsonb))), 0)::int AS serialized_candidate_count
            FROM stages
            GROUP BY stage->>'name'
            ORDER BY stage->>'name'
            """,
            params,
        )
        score_rows = self._execute_all(
            f"""
            WITH filtered AS (
                SELECT e.execution_id, e.retrieval_lineage
                FROM query_analytics_executions e
                WHERE {where} AND e.retrieval_lineage IS NOT NULL
            ), stages AS (
                SELECT f.execution_id, s.stage
                FROM filtered f
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(f.retrieval_lineage->'stages', '[]'::jsonb)
                ) AS s(stage)
            ), candidates AS (
                SELECT
                    execution_id,
                    stage->>'name' AS name,
                    NULLIF(candidate->>'retrieval_score', '')::float8 AS retrieval_score,
                    NULLIF(candidate->>'rerank_score', '')::float8 AS rerank_score,
                    NULLIF(candidate->>'rerank_adjusted_score', '')::float8 AS adjusted_score
                FROM stages
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(stage->'candidates', '[]'::jsonb)
                ) AS c(candidate)
            )
            SELECT
                name,
                COUNT(retrieval_score)::int AS retrieval_count,
                AVG(retrieval_score)::float8 AS retrieval_mean,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY retrieval_score)
                    FILTER (WHERE retrieval_score IS NOT NULL)::float8 AS retrieval_p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY retrieval_score)
                    FILTER (WHERE retrieval_score IS NOT NULL)::float8 AS retrieval_p95,
                COUNT(rerank_score)::int AS rerank_count,
                AVG(rerank_score)::float8 AS rerank_mean,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY rerank_score)
                    FILTER (WHERE rerank_score IS NOT NULL)::float8 AS rerank_p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY rerank_score)
                    FILTER (WHERE rerank_score IS NOT NULL)::float8 AS rerank_p95,
                COUNT(adjusted_score)::int AS adjusted_count,
                AVG(adjusted_score)::float8 AS adjusted_mean,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY adjusted_score)
                    FILTER (WHERE adjusted_score IS NOT NULL)::float8 AS adjusted_p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY adjusted_score)
                    FILTER (WHERE adjusted_score IS NOT NULL)::float8 AS adjusted_p95,
                {_score_bucket_select("retrieval_score", "retrieval")},
                {_score_bucket_select("rerank_score", "rerank")},
                {_score_bucket_select("adjusted_score", "adjusted")}
            FROM candidates
            GROUP BY name
            ORDER BY name
            """,
            params,
        )
        rank_row = self._execute_one(
            f"""
            WITH filtered AS (
                SELECT e.execution_id, e.retrieval_lineage
                FROM query_analytics_executions e
                WHERE {where} AND e.retrieval_lineage IS NOT NULL
            ), stages AS (
                SELECT f.execution_id, s.stage
                FROM filtered f
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(f.retrieval_lineage->'stages', '[]'::jsonb)
                ) AS s(stage)
            ), candidates AS (
                SELECT
                    execution_id,
                    stage->>'name' AS name,
                    (stage->>'attempt')::int AS attempt,
                    candidate->>'candidate_key' AS candidate_key,
                    (candidate->>'rank')::int AS rank
                FROM stages
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(stage->'candidates', '[]'::jsonb)
                ) AS c(candidate)
                WHERE COALESCE((stage->>'truncated')::bool, FALSE) = FALSE
            ), inputs AS (
                SELECT * FROM candidates WHERE name = 'rerank_input'
            ), outputs AS (
                SELECT * FROM candidates WHERE name = 'reranked'
            ), movements AS (
                SELECT outputs.rank - inputs.rank AS movement
                FROM inputs
                JOIN outputs USING (execution_id, attempt, candidate_key)
            )
            SELECT
                COUNT(*)::int AS count,
                AVG(ABS(movement))::float8 AS mean_absolute,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY ABS(movement))::float8 AS p50_absolute,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY ABS(movement))::float8 AS p95_absolute,
                COUNT(*) FILTER (WHERE movement < 0)::int AS promoted,
                COUNT(*) FILTER (WHERE movement > 0)::int AS demoted,
                COUNT(*) FILTER (WHERE movement = 0)::int AS unchanged
            FROM movements
            """,
            params,
        )
        utilization_row = self._execute_one(
            f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE retrieval_lineage->'generation'->>'status' = 'available'
                      AND retrieval_lineage->'citation'->>'status' = 'available'
                )::int AS execution_count,
                COALESCE(SUM((retrieval_lineage->'generation'->>'source_count')::int) FILTER (
                    WHERE retrieval_lineage->'generation'->>'status' = 'available'
                      AND retrieval_lineage->'citation'->>'status' = 'available'
                ), 0)::int AS sent_source_count,
                COALESCE(SUM((retrieval_lineage->'citation'->>'cited_source_count')::int) FILTER (
                    WHERE retrieval_lineage->'generation'->>'status' = 'available'
                      AND retrieval_lineage->'citation'->>'status' = 'available'
                ), 0)::int AS cited_source_count
            FROM query_analytics_executions e
            WHERE {where} AND retrieval_lineage IS NOT NULL
            """,
            params,
        )
        timing_rows = self._execute_all(
            f"""
            WITH filtered AS (
                SELECT e.execution_id, e.retrieval_lineage
                FROM query_analytics_executions e
                WHERE {where} AND e.retrieval_lineage IS NOT NULL
            ), timings AS (
                SELECT f.execution_id, timing
                FROM filtered f
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(f.retrieval_lineage->'performance'->'node_timings', '[]'::jsonb)
                ) AS t(timing)
            ), per_execution AS (
                SELECT execution_id, timing->>'node' AS node,
                    SUM(NULLIF(timing->>'duration_ms', '')::float8) AS duration_ms,
                    COUNT(NULLIF(timing->>'duration_ms', '')) AS sample_count
                FROM timings
                GROUP BY execution_id, timing->>'node'
            )
            SELECT
                node,
                COUNT(*)::int AS execution_count,
                SUM(sample_count)::int AS duration_count,
                percentile_cont(0.50) WITHIN GROUP (
                    ORDER BY duration_ms
                )::float8 AS p50_ms,
                percentile_cont(0.95) WITHIN GROUP (
                    ORDER BY duration_ms
                )::float8 AS p95_ms
            FROM per_execution
            GROUP BY node
            ORDER BY node
            """,
            params,
        )
        score_by_name = {row["name"]: row for row in score_rows}
        stages = []
        for row in stage_rows:
            score = score_by_name.get(row["name"], {})
            stages.append(
                AnalyticsStageDiagnostics(
                    name=row["name"],
                    execution_count=int(row["execution_count"]),
                    candidate_count=int(row["candidate_count"]),
                    serialized_candidate_count=int(row["serialized_candidate_count"]),
                    retrieval_score=_postgres_score_stats(score, "retrieval"),
                    rerank_score=_postgres_score_stats(score, "rerank"),
                    adjusted_rerank_score=_postgres_score_stats(score, "adjusted"),
                )
            )
        return AnalyticsDiagnostics(
            capture_status_counts=tuple(
                (str(row["status"]), int(row["count"])) for row in status_rows
            ),
            stages=tuple(stages),
            timings=tuple(
                AnalyticsTimingDiagnostics(
                    node=row["node"],
                    execution_count=int(row["execution_count"]),
                    duration_count=int(row["duration_count"]),
                    p50_ms=row["p50_ms"],
                    p95_ms=row["p95_ms"],
                )
                for row in timing_rows
            ),
            rank_movement=AnalyticsRankMovement(
                status="available" if int(rank_row["count"] or 0) else "unavailable",
                count=int(rank_row["count"] or 0),
                mean_absolute=rank_row["mean_absolute"],
                p50_absolute=rank_row["p50_absolute"],
                p95_absolute=rank_row["p95_absolute"],
                promoted=int(rank_row["promoted"] or 0),
                demoted=int(rank_row["demoted"] or 0),
                unchanged=int(rank_row["unchanged"] or 0),
            ),
            evidence_utilization=AnalyticsEvidenceUtilization(
                status="available" if int(utilization_row["execution_count"] or 0) else "unavailable",
                execution_count=int(utilization_row["execution_count"] or 0),
                sent_source_count=int(utilization_row["sent_source_count"] or 0),
                cited_source_count=int(utilization_row["cited_source_count"] or 0),
                utilization_rate=(
                    int(utilization_row["cited_source_count"] or 0)
                    / int(utilization_row["sent_source_count"])
                    if int(utilization_row["sent_source_count"] or 0)
                    else None
                ),
            ),
            quality=AnalyticsQualityDiagnostics(
                status_counts=tuple(
                    (str(row["status"]), int(row["count"]))
                    for row in quality_status_rows
                ),
                method_counts=tuple(
                    (str(row["method"]), int(row["count"]))
                    for row in quality_method_rows
                ),
                support_status_counts=tuple(
                    (str(row["support_status"]), int(row["count"]))
                    for row in support_rows
                ),
                score=AnalyticsScoreStats(
                    count=int(quality_score_row["faithfulness_count"] or 0),
                    mean=quality_score_row["faithfulness_mean"],
                    p50=quality_score_row["faithfulness_p50"],
                    p95=quality_score_row["faithfulness_p95"],
                    buckets=tuple(
                        (label, int(quality_score_row.get(suffix) or 0))
                        for label, suffix in (
                            ("0.0-0.2", "faithfulness_bucket_0_2"),
                            ("0.2-0.4", "faithfulness_bucket_2_4"),
                            ("0.4-0.6", "faithfulness_bucket_4_6"),
                            ("0.6-0.8", "faithfulness_bucket_6_8"),
                            ("0.8-1.0", "faithfulness_bucket_8_10"),
                            ("other", "faithfulness_bucket_other"),
                        )
                    ),
                ),
                checked_count=sum(
                    int(row["count"])
                    for row in quality_status_rows
                    if row["status"] == "checked"
                ),
                applicable_count=sum(
                    int(row["count"])
                    for row in quality_status_rows
                    if row["status"] not in {"not_measured", "skipped"}
                ),
                claim_ledger=AnalyticsClaimLedger(
                    status="available" if int(claim_ledger_row["execution_count"] or 0) else "unavailable",
                    execution_count=int(claim_ledger_row["execution_count"] or 0),
                    applicable_claim_count=int(claim_ledger_row["applicable_claim_count"] or 0),
                    supported_claim_count=int(claim_ledger_row["supported_claim_count"] or 0),
                    unsupported_claim_count=int(claim_ledger_row["unsupported_claim_count"] or 0),
                    unknown_claim_count=int(claim_ledger_row["unknown_claim_count"] or 0),
                    cited_claim_count=int(claim_ledger_row["cited_claim_count"] or 0),
                    uncited_claim_count=int(claim_ledger_row["uncited_claim_count"] or 0),
                    valid_quote_count=int(claim_ledger_row["valid_quote_count"] or 0),
                    support_rate=AnalyticsRate(
                        int(claim_ledger_row["supported_claim_count"] or 0),
                        int(claim_ledger_row["applicable_claim_count"] or 0),
                    ),
                    citation_coverage=AnalyticsRate(
                        int(claim_ledger_row["cited_claim_count"] or 0),
                        int(claim_ledger_row["applicable_claim_count"] or 0),
                    ),
                ),
            ),
            documents=AnalyticsDocumentDiagnostics(
                status="available" if documents_per_query_row["count"] else "unavailable",
                documents_per_query=AnalyticsCountStats(
                    count=int(documents_per_query_row["count"] or 0),
                    mean=documents_per_query_row["mean"],
                    p50=documents_per_query_row["p50"],
                    p95=documents_per_query_row["p95"],
                    buckets=tuple(
                        (label, int(documents_per_query_row.get(suffix) or 0))
                        for label, suffix in (("1", "bucket_1"), ("2", "bucket_2"), ("3", "bucket_3"), ("4", "bucket_4"), ("5+", "bucket_5_plus"))
                    ),
                ),
                top_documents=tuple(
                    AnalyticsDocumentUsage(
                        document_key=str(row["document_key"]),
                        document_title=row["document_title"],
                        generation_id=row["generation_id"],
                        execution_count=int(row["execution_count"]),
                        candidate_count=int(row["candidate_count"]),
                    )
                    for row in document_rows
                ),
                top_k_turnover=AnalyticsTopKTurnover(
                    status="available" if int(turnover_row["comparable_attempt_count"] or 0) else "unavailable",
                    comparable_attempt_count=int(turnover_row["comparable_attempt_count"] or 0),
                    mean_overlap=turnover_row["mean_overlap"],
                    p50_overlap=turnover_row["p50_overlap"],
                    p95_overlap=turnover_row["p95_overlap"],
                    mean_added=turnover_row["mean_added"],
                    mean_dropped=turnover_row["mean_dropped"],
                ),
            ),
            cohorts=tuple(
                AnalyticsCohortObservation(
                    model_cohort=str(row["model_cohort"]),
                    configuration_digest=str(row["configuration_digest"]),
                    application_image_digest=row["application_image_digest"],
                    execution_count=int(row["execution_count"]),
                    first_observed_at=row["first_observed_at"],
                )
                for row in cohort_rows
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
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        with self._connect() as conn:
            expired_lineages = conn.execute(
                """
                WITH expired AS (
                    SELECT execution_id FROM query_analytics_executions
                    WHERE lifecycle = 'terminal' AND finished_at < %s
                      AND retrieval_lineage IS NOT NULL
                      AND retrieval_lineage_status <> 'expired'
                    ORDER BY finished_at, execution_id
                    LIMIT %s FOR UPDATE SKIP LOCKED
                )
                UPDATE query_analytics_executions AS execution
                SET retrieval_lineage_status = 'expired',
                    retrieval_lineage = jsonb_build_object(
                        'schema_version', 1, 'status', 'expired',
                        'performance', COALESCE(execution.retrieval_lineage->'performance', '{}'::jsonb)
                    )
                FROM expired WHERE execution.execution_id = expired.execution_id
                RETURNING execution.execution_id
                """,
                (lineage_before or as_of - timedelta(days=7), batch_size),
            ).fetchall()
            reconciled = conn.execute(
                """
                WITH due AS (
                    SELECT execution_id
                    FROM query_analytics_executions
                    WHERE lifecycle = 'in_flight'
                      AND last_heartbeat_at IS NOT NULL
                      AND reconciliation_deadline_at IS NOT NULL
                      AND reconciliation_deadline_at <= %s
                    ORDER BY reconciliation_deadline_at, execution_id
                    LIMIT %s FOR UPDATE SKIP LOCKED
                )
                UPDATE query_analytics_executions AS execution
                SET lifecycle = 'terminal',
                    finished_at = %s,
                    outcome = 'interrupted',
                    degraded = TRUE,
                    reason_code = 'analytics_heartbeat_expired',
                    degraded_reason = 'analytics_heartbeat_expired'
                FROM due
                WHERE execution.execution_id = due.execution_id AND execution.lifecycle = 'in_flight'
                RETURNING execution.execution_id
                """,
                (as_of, batch_size, as_of),
            ).fetchall() if reconcile else []
            remaining = max(0, batch_size - len(reconciled))
            deleted_executions = conn.execute(
                """
                WITH doomed AS (
                    SELECT execution_id
                    FROM query_analytics_executions
                    WHERE lifecycle = 'terminal' AND started_at < %s
                      AND (reason_code IS DISTINCT FROM 'analytics_heartbeat_expired' OR finished_at < %s)
                    ORDER BY started_at, execution_id
                    LIMIT %s FOR UPDATE SKIP LOCKED
                )
                DELETE FROM query_analytics_executions AS execution
                USING doomed
                WHERE execution.execution_id = doomed.execution_id
                RETURNING execution.execution_id
                """,
                (retention_before, retention_before, remaining),
            ).fetchall() if remaining else []
            deleted_boundary_events = conn.execute(
                """
                WITH doomed AS (
                    SELECT event_id
                    FROM query_analytics_boundary_events
                    WHERE occurred_at < %s
                    ORDER BY occurred_at, event_id
                    LIMIT %s
                )
                DELETE FROM query_analytics_boundary_events AS event
                USING doomed
                WHERE event.event_id = doomed.event_id
                RETURNING event.event_id
                """,
                (retention_before, batch_size),
            ).fetchall()
        return AnalyticsMaintenanceResult(
            reconciled_execution_count=len(reconciled),
            deleted_execution_count=len(deleted_executions),
            deleted_boundary_event_count=len(deleted_boundary_events),
            expired_lineage_count=len(expired_lineages),
        )

    def _count(self, filters: AnalyticsFilters) -> int:
        where, params = _where(filters)
        row = self._execute_one(
            f"SELECT COUNT(*)::int AS total FROM query_analytics_executions WHERE {where}",
            params,
        )
        return int(row["total"])

def _where(filters: AnalyticsFilters, *, alias: str | None = None) -> tuple[str, tuple[Any, ...]]:
    prefix = f"{alias}." if alias else ""
    clauses = [f"{prefix}started_at >= %s", f"{prefix}started_at < %s"]
    params: list[Any] = [filters.created_from, filters.created_to]
    if filters.as_of is not None:
        clauses.append(f"{prefix}created_at <= %s")
        params.append(filters.as_of)
    for column, value in (
        ("origin", filters.origin),
        ("work_kind", filters.work_kind),
        ("actor_id", filters.actor_id),
        ("group_path", filters.group_path),
        ("outcome", filters.outcome),
        ("resolved_source_mode", filters.source_mode),
        ("final_intent", filters.intent),
        ("model_cohort", filters.model_cohort),
        ("configuration_digest", filters.configuration_digest),
    ):
        if value is not None:
            clauses.append(f"{prefix}{column} = %s")
            params.append(value)
    return " AND ".join(clauses), tuple(params)


def _record_from_row(row: dict[str, Any]) -> AnalyticsExecutionRecord:
    values = {key: row.get(key) for key in AnalyticsExecutionRecord.__dataclass_fields__}
    for key in ("execution_id", "trace_id", "session_id", "actor_id"):
        values[key] = str(values[key])
    values["retrieval_lineage_status"] = row.get("retrieval_lineage_status") or "not_captured"
    if isinstance(values["retrieval_lineage"], str):
        values["retrieval_lineage"] = json.loads(values["retrieval_lineage"])
    if isinstance(values["cohort_snapshot"], str):
        values["cohort_snapshot"] = json.loads(values["cohort_snapshot"])
    return AnalyticsExecutionRecord(**values)


def _postgres_score_stats(row: dict[str, Any], prefix: str) -> AnalyticsScoreStats:
    return AnalyticsScoreStats(
        count=int(row.get(f"{prefix}_count") or 0),
        mean=row.get(f"{prefix}_mean"),
        p50=row.get(f"{prefix}_p50"),
        p95=row.get(f"{prefix}_p95"),
        buckets=tuple(
            (label, int(row.get(f"{prefix}_{suffix}") or 0))
            for label, suffix in (
                ("0.0-0.2", "bucket_0_2"),
                ("0.2-0.4", "bucket_2_4"),
                ("0.4-0.6", "bucket_4_6"),
                ("0.6-0.8", "bucket_6_8"),
                ("0.8-1.0", "bucket_8_10"),
                ("other", "bucket_other"),
            )
        ),
    )


def _score_bucket_select(column: str, prefix: str) -> str:
    return ",\n                ".join(
        [
            f"COUNT(*) FILTER (WHERE {column} >= 0 AND {column} < 0.2)::int AS {prefix}_bucket_0_2",
            f"COUNT(*) FILTER (WHERE {column} >= 0.2 AND {column} < 0.4)::int AS {prefix}_bucket_2_4",
            f"COUNT(*) FILTER (WHERE {column} >= 0.4 AND {column} < 0.6)::int AS {prefix}_bucket_4_6",
            f"COUNT(*) FILTER (WHERE {column} >= 0.6 AND {column} < 0.8)::int AS {prefix}_bucket_6_8",
            f"COUNT(*) FILTER (WHERE {column} >= 0.8 AND {column} <= 1.0)::int AS {prefix}_bucket_8_10",
            f"COUNT(*) FILTER (WHERE {column} < 0 OR {column} > 1.0)::int AS {prefix}_bucket_other",
        ]
    )


def _count_bucket_select(column: str) -> str:
    return ",\n                ".join(
        [
            f"COUNT(*) FILTER (WHERE {column} >= 1 AND {column} < 2)::int AS bucket_1",
            f"COUNT(*) FILTER (WHERE {column} >= 2 AND {column} < 3)::int AS bucket_2",
            f"COUNT(*) FILTER (WHERE {column} >= 3 AND {column} < 4)::int AS bucket_3",
            f"COUNT(*) FILTER (WHERE {column} >= 4 AND {column} < 5)::int AS bucket_4",
            f"COUNT(*) FILTER (WHERE {column} >= 5)::int AS bucket_5_plus",
        ]
    )
