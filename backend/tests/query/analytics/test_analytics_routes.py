from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from rag.auth.dependencies import require_platform_admin_user
from rag.query.analytics.adapters.memory import InMemoryAnalyticsRepository
from rag.query.analytics.models import AnalyticsExecutionRecord
from rag.query.analytics.routes import router
from rag.query.analytics.repository import get_analytics_repository


def test_platform_admin_can_read_filtered_summary_and_execution_list() -> None:
    repository = InMemoryAnalyticsRepository()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    repository.start_execution(
        AnalyticsExecutionRecord(
            execution_id="00000000-0000-0000-0000-000000000001",
            trace_id="10000000-0000-0000-0000-000000000001",
            session_id="20000000-0000-0000-0000-000000000001",
            actor_id="30000000-0000-0000-0000-000000000001",
            permission_version=1,
            origin="chat",
            work_kind="answer",
            group_path="/finance",
            lifecycle="terminal",
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=1),
            outcome="complete",
            answer_status="complete",
            latency_ms=100,
            evidence_source_count=2,
            cited_source_count=0,
            retrieval_lineage_status="available",
            retrieval_lineage={"stage_count": 1, "stages": []},
        )
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_analytics_repository] = lambda: repository
    app.dependency_overrides[require_platform_admin_user] = lambda: object()

    with TestClient(app) as client:
        params = {"from": "2025-12-31T00:00:00Z", "to": "2026-01-03T00:00:00Z", "group_path": "/finance"}
        summary = client.get("/api/v1/admin/query-analytics/summary", params=params)
        series = client.get("/api/v1/admin/query-analytics/series", params=params)
        executions = client.get("/api/v1/admin/query-analytics/executions", params=params)
        diagnostics = client.get("/api/v1/admin/query-analytics/diagnostics", params=params)
        detail = client.get(
            "/api/v1/admin/query-analytics/executions/00000000-0000-0000-0000-000000000001"
        )

    assert summary.status_code == 200
    assert summary.json()["complete_rate"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert series.status_code == 200
    assert series.json()["bucket_size"] == "day"
    assert series.json()["buckets"]
    assert diagnostics.status_code == 200
    assert diagnostics.json()["capture_status_counts"]["available"] == 1
    assert executions.status_code == 200
    assert executions.json()["total"] == 1
    assert executions.json()["items"][0]["group_path"] == "/finance"
    assert executions.json()["items"][0]["review_reasons"] == ["missing_citation"]
    assert executions.json()["items"][0]["retrieval_lineage"] is None
    assert detail.status_code == 200
    assert detail.json()["retrieval_lineage_status"] == "available"
    assert detail.json()["retrieval_lineage"]["stage_count"] == 1
    assert "/api/v1/admin/query-analytics/series" in app.openapi()["paths"]


def test_analytics_window_is_bounded_and_platform_admin_gate_is_enforced() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_analytics_repository] = InMemoryAnalyticsRepository
    app.dependency_overrides[require_platform_admin_user] = lambda: object()

    with TestClient(app) as client:
        too_large = client.get(
            "/api/v1/admin/query-analytics/summary",
            params={"from": "2025-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
        )
        invalid_filter = client.get(
            "/api/v1/admin/query-analytics/summary",
            params={"outcome": "unknown"},
        )
        invalid_page = client.get(
            "/api/v1/admin/query-analytics/executions",
            params={"limit": 101},
        )
        app.dependency_overrides[require_platform_admin_user] = lambda: (_ for _ in ()).throw(HTTPException(status_code=403))
        forbidden = client.get("/api/v1/admin/query-analytics/summary")

    assert too_large.status_code == 400
    assert invalid_filter.status_code == 422
    assert invalid_page.status_code == 422
    assert forbidden.status_code == 403
