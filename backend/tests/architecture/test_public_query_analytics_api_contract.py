"""Regression contract for the public query analytics API."""

from apps.api.main import create_app


def test_query_analytics_routes_are_platform_admin_read_contracts() -> None:
    paths = {
        "/api/v1/admin/query-analytics/summary": "AnalyticsSummaryResponse",
        "/api/v1/admin/query-analytics/executions": "AnalyticsExecutionListResponse",
        "/api/v1/admin/query-analytics/series": "AnalyticsSeriesResponse",
        "/api/v1/admin/query-analytics/diagnostics": "AnalyticsDiagnosticsResponse",
        "/api/v1/admin/query-analytics/executions/{execution_id}": "AnalyticsExecutionResponse",
    }
    specification = create_app().openapi()

    for path, response_schema in paths.items():
        operation = specification["paths"][path]["get"]
        assert operation["tags"] == ["query-analytics"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
            f"#/components/schemas/{response_schema}"
        )
        assert "422" in operation["responses"]


def test_analytics_defaults_and_snapshot_are_part_of_the_public_contract():
    specification = create_app().openapi()
    operation = specification["paths"]["/api/v1/admin/query-analytics/executions"]["get"]
    parameters = {parameter["name"]: parameter["schema"] for parameter in operation["parameters"]}
    assert parameters["origin"]["default"] == "chat"
    assert parameters["work_kind"]["default"] == "answer"
    assert "as_of" in parameters
    assert "reason_code" in specification["components"]["schemas"]["AnalyticsExecutionResponse"]["properties"]
    properties = specification["components"]["schemas"]["AnalyticsExecutionResponse"]["properties"]
    assert properties["liveness_status"]["enum"] == ["untracked", "active", "heartbeat_expired", "finished"]
    assert "last_heartbeat_at" in properties


def test_analytics_retention_has_an_independent_background_entrypoint():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    compose = (root / "docker-compose.yml").read_text()
    service = compose.split("  query-analytics-maintenance:\n", 1)[1].split("\n  ingestion-worker:", 1)[0]
    assert '"apps.background.query_analytics_cleanup"' in service
    assert '"--healthcheck"' in service
    assert "condition: service_healthy" in service
    assert "QUERY_ANALYTICS_LINEAGE_RETENTION_DAYS:" in compose
