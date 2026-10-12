from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from rag.query.analytics.adapters.memory import InMemoryAnalyticsRepository
from rag.query.analytics.adapters.postgres import _record_from_row
from rag.query.analytics.models import (
    AnalyticsBoundaryEvent,
    AnalyticsExecutionRecord,
    AnalyticsFilters,
)


def _record(index: int, *, started_at: datetime, outcome: str = "complete") -> AnalyticsExecutionRecord:
    terminal = outcome != "in_flight"
    return AnalyticsExecutionRecord(
        execution_id=f"00000000-0000-0000-0000-{index:012d}",
        trace_id=f"10000000-0000-0000-0000-{index:012d}",
        session_id=f"20000000-0000-0000-0000-{index:012d}",
        actor_id=f"user-{index % 2}",
        permission_version=1,
        origin="chat",
        work_kind="answer",
        group_path="/ops",
        lifecycle="terminal" if terminal else "in_flight",
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1) if terminal else None,
        outcome=outcome if terminal else None,
        answer_status=outcome if terminal else None,
        latency_ms=index * 100 if terminal else None,
        verification_status="checked" if terminal and index % 2 else "skipped",
    )


def test_memory_repository_is_idempotent_and_reports_explicit_rates() -> None:
    repository = InMemoryAnalyticsRepository()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    repository.start_execution(_record(1, started_at=started_at))
    repository.start_execution(_record(1, started_at=started_at, outcome="partial"))
    repository.finish_execution(
        "00000000-0000-0000-0000-000000000001",
        finished_at=started_at + timedelta(seconds=1),
        outcome="complete",
        answer_status="complete",
        latency_ms=100,
        verification_status="checked",
    )
    repository.finish_execution(
        "00000000-0000-0000-0000-000000000001",
        finished_at=started_at + timedelta(seconds=2),
        outcome="partial",
        answer_status="partial",
        latency_ms=200,
    )
    repository.start_execution(_record(2, started_at=started_at + timedelta(minutes=1), outcome="partial"))
    repository.start_execution(_record(3, started_at=started_at + timedelta(minutes=2), outcome="abstained"))
    repository.start_execution(_record(4, started_at=started_at + timedelta(minutes=3), outcome="system_error"))
    repository.start_execution(_record(5, started_at=started_at + timedelta(minutes=4), outcome="cancelled"))
    repository.start_execution(
        replace(
            _record(6, started_at=started_at + timedelta(minutes=5), outcome="artifact_submitted"),
            work_kind="artifact_submission",
        )
    )

    summary = repository.summarize_executions(
        filters=AnalyticsFilters(
            created_from=started_at - timedelta(days=1),
            created_to=started_at + timedelta(days=1),
        )
    )

    assert summary.total_executions == 6
    assert summary.terminal_executions == 6
    assert summary.answer_executions == 5
    assert summary.complete == 1
    assert summary.partial == 1
    assert summary.abstained == 1
    assert summary.system_error == 1
    assert summary.cancelled == 1
    assert summary.complete_rate.numerator == 1
    assert summary.complete_rate.denominator == 5
    assert summary.complete_rate.value == 0.2
    assert summary.verification_coverage.numerator == 3
    assert summary.verification_coverage.denominator == 3
    assert summary.p50_latency_ms == 300
    assert summary.p95_latency_ms == 480


def test_memory_repository_filters_scope_and_orders_stably() -> None:
    repository = InMemoryAnalyticsRepository()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    repository.start_execution(_record(1, started_at=started_at, outcome="complete"))
    repository.start_execution(_record(2, started_at=started_at + timedelta(hours=1), outcome="abstained"))

    page = repository.list_executions(
        filters=AnalyticsFilters(
            created_from=started_at,
            created_to=started_at + timedelta(days=1),
            outcome="abstained",
            group_path="/ops",
        ),
        limit=50,
        offset=0,
    )

    assert page.total == 1
    assert [item.outcome for item in page.items] == ["abstained"]


def test_memory_series_preserves_empty_buckets_and_answer_latency() -> None:
    repository = InMemoryAnalyticsRepository()
    started_at = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    repository.start_execution(_record(1, started_at=started_at, outcome="complete"))

    series = repository.series_executions(
        filters=AnalyticsFilters(
            created_from=started_at - timedelta(hours=1),
            created_to=started_at + timedelta(hours=2),
        ),
        bucket_size="hour",
    )

    assert len(series.buckets) == 4
    assert [bucket.total_executions for bucket in series.buckets] == [0, 1, 0, 0]
    assert series.buckets[1].answer_executions == 1
    assert series.buckets[1].p50_latency_ms == 100
    assert series.buckets[0].p95_latency_ms is None


def test_memory_quality_diagnostics_keep_checked_scores_qualified() -> None:
    repository = InMemoryAnalyticsRepository()
    started_at = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    checked = replace(
        _record(8, started_at=started_at),
        verification_status="checked",
        verification_method="deterministic",
        faithfulness_score=0.75,
        model_cohort="models-a",
        configuration_digest="config-a",
        application_image_digest="sha256:image-a",
        retrieval_lineage={
            "stages": [
                {
                    "name": "retrieved",
                    "attempt": 0,
                    "status": "completed",
                    "truncated": False,
                    "candidates": [
                        {"candidate_key": "g:doc-a:a", "doc_id": "doc-a", "doc_title": "A", "index_generation_id": "g"},
                        {"candidate_key": "g:doc-a:b", "doc_id": "doc-a", "doc_title": "A", "index_generation_id": "g"},
                        {"candidate_key": "g:doc-b:c", "doc_id": "doc-b", "doc_title": "B", "index_generation_id": "g"},
                    ],
                },
                {
                    "name": "rerank_input",
                    "attempt": 0,
                    "status": "completed",
                    "truncated": False,
                    "candidates": [{"candidate_key": key} for key in ("a", "b", "c")],
                },
                {
                    "name": "final_evidence",
                    "attempt": 0,
                    "status": "completed",
                    "truncated": False,
                    "candidates": [{"candidate_key": key} for key in ("a", "d")],
                },
            ],
            "quality": {
                "support_status_counts": {"verified": 2, "semantic_fallback": 1},
                "claim_ledger": {
                    "status": "captured",
                    "applicable_claims": 4,
                    "supported_claims": 3,
                    "unsupported_claims": 1,
                    "unknown_claims": 0,
                    "cited_claims": 3,
                    "uncited_claims": 1,
                    "valid_quotes": 3,
                },
            }
        },
    )
    skipped = replace(
        _record(9, started_at=started_at + timedelta(minutes=1)),
        verification_status="skipped",
        faithfulness_score=0.0,
    )
    repository.start_execution(checked)
    repository.start_execution(skipped)
    filters = AnalyticsFilters(
        created_from=started_at - timedelta(hours=1),
        created_to=started_at + timedelta(hours=1),
    )

    diagnostics = repository.diagnose_executions(filters=filters)
    quality = diagnostics.quality
    assert dict(quality.status_counts) == {"checked": 1, "skipped": 1}
    assert dict(quality.method_counts) == {"deterministic": 1}
    assert dict(quality.support_status_counts) == {"semantic_fallback": 1, "verified": 2}
    assert quality.checked_count == 1
    assert quality.claim_ledger.execution_count == 1
    assert quality.claim_ledger.support_rate.value == 0.75
    assert quality.claim_ledger.citation_coverage.value == 0.75
    assert quality.applicable_count == 1
    assert quality.score.count == 1
    assert quality.score.mean == 0.75
    assert quality.checked_count == 1

    assert diagnostics.documents.documents_per_query.mean == 2
    assert diagnostics.documents.top_documents[0].document_key == "g:doc-a"
    assert diagnostics.documents.top_documents[0].candidate_count == 2
    assert diagnostics.documents.top_k_turnover.comparable_attempt_count == 1
    assert diagnostics.documents.top_k_turnover.mean_overlap == 0.25
    assert diagnostics.documents.top_k_turnover.mean_added == 1
    assert diagnostics.documents.top_k_turnover.mean_dropped == 2
    assert diagnostics.cohorts[0].configuration_digest == "config-a"
    assert diagnostics.cohorts[0].execution_count == 1

    series = repository.series_executions(filters=filters, bucket_size="hour")
    assert series.buckets[1].verification_checked == 1
    assert series.buckets[1].verification_applicable == 1
    assert series.buckets[1].faithfulness_score_mean == 0.75


def test_memory_maintenance_reconciles_and_expires_in_bounded_batches() -> None:
    repository = InMemoryAnalyticsRepository()
    as_of = datetime(2026, 2, 1, tzinfo=UTC)
    old_started_at = as_of - timedelta(days=31)
    due = _record(1, started_at=as_of - timedelta(hours=2), outcome="in_flight")
    due = replace(due, last_heartbeat_at=as_of - timedelta(hours=1), reconciliation_deadline_at=as_of - timedelta(minutes=1))
    old_terminal = _record(2, started_at=old_started_at, outcome="complete")
    fresh = _record(3, started_at=as_of - timedelta(hours=1), outcome="complete")
    future = replace(
        _record(4, started_at=as_of - timedelta(hours=1), outcome="in_flight"),
        reconciliation_deadline_at=as_of + timedelta(hours=1),
        last_heartbeat_at=as_of,
    )
    for record in (due, old_terminal, fresh, future):
        repository.start_execution(record)
    repository.record_boundary_event(
        AnalyticsBoundaryEvent(
            event_id="old-boundary",
            occurred_at=old_started_at,
            route_path="/api/v1/query",
            status_code=422,
            reason_code="validation_error",
        )
    )

    result = repository.maintain(
        as_of=as_of,
        retention_before=as_of - timedelta(days=30),
        batch_size=10,
    )

    assert result.reconciled_execution_count == 1
    assert result.deleted_execution_count == 1
    assert result.deleted_boundary_event_count == 1
    assert repository.get_execution(due.execution_id).outcome == "interrupted"
    assert repository.get_execution(due.execution_id).degraded_reason == "analytics_heartbeat_expired"
    assert repository.get_execution(old_terminal.execution_id) is None
    assert repository.get_execution(fresh.execution_id) is not None
    assert repository.get_execution(future.execution_id).lifecycle == "in_flight"
    assert repository.maintain(
        as_of=as_of,
        retention_before=as_of - timedelta(days=30),
        batch_size=10,
    ) == repository.maintain(
        as_of=as_of,
        retention_before=as_of - timedelta(days=30),
        batch_size=10,
    )


def test_postgres_deserialization_normalizes_uuid_identifiers() -> None:
    record = _record(7, started_at=datetime(2026, 1, 1, tzinfo=UTC))
    row = asdict(record)
    row.update({
        "execution_id": UUID(record.execution_id),
        "trace_id": UUID(record.trace_id),
        "session_id": UUID(record.session_id),
        "actor_id": UUID("00000000-0000-0000-0000-000000000007"),
    })

    deserialized = _record_from_row(row)

    assert deserialized.execution_id == record.execution_id
    assert isinstance(deserialized.execution_id, str)
    assert isinstance(deserialized.actor_id, str)
