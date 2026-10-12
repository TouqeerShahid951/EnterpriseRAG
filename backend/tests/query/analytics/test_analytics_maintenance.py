from datetime import UTC, datetime

from rag.query.analytics.models import AnalyticsMaintenanceResult
from rag.ops import query_analytics_maintenance


def test_run_once_passes_retention_and_batch_configuration(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class Repository:
        def maintain(self, **kwargs):
            calls.append(kwargs)
            return AnalyticsMaintenanceResult(reconciled_execution_count=2)

    monkeypatch.setattr(query_analytics_maintenance, "get_analytics_repository", lambda: Repository())
    monkeypatch.setattr(query_analytics_maintenance.settings, "query_analytics_retention_days", 30)
    monkeypatch.setattr(query_analytics_maintenance.settings, "query_analytics_lineage_retention_days", 7)
    monkeypatch.setattr(query_analytics_maintenance.settings, "query_analytics_maintenance_batch_size", 25)
    as_of = datetime(2026, 2, 1, tzinfo=UTC)

    result = query_analytics_maintenance.run_once(as_of=as_of)

    assert result.reconciled_execution_count == 2
    assert calls == [{
        "as_of": as_of,
        "retention_before": datetime(2026, 1, 2, tzinfo=UTC),
        "lineage_before": datetime(2026, 1, 25, tzinfo=UTC),
        "batch_size": 25,
        "reconcile": True,
    }]


def test_scheduled_cleanup_heartbeats_only_after_a_successful_cycle(monkeypatch):
    import sys
    import pytest
    from apps.background import query_analytics_cleanup

    events = []
    monkeypatch.setattr(sys, "argv", ["query_analytics_cleanup", "--once"])
    monkeypatch.setattr(query_analytics_cleanup, "run_once", lambda: AnalyticsMaintenanceResult(expired_lineage_count=2))
    monkeypatch.setattr(query_analytics_cleanup, "heartbeat", lambda: events.append("success"))
    assert query_analytics_cleanup.main() == 0
    assert events == ["success"]

    def unavailable():
        raise RuntimeError("test storage unavailable")

    monkeypatch.setattr(query_analytics_cleanup, "run_once", unavailable)
    with pytest.raises(RuntimeError):
        query_analytics_cleanup.main()
    assert events == ["success"]
