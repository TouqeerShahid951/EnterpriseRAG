from starlette.requests import Request

from apps.api import main as api_main
from rag.query.analytics.adapters.memory import InMemoryAnalyticsRepository


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
            "scheme": "http",
        }
    )


def test_query_boundary_events_are_recorded_without_recording_other_api_errors(monkeypatch) -> None:
    repository = InMemoryAnalyticsRepository()
    monkeypatch.setattr(api_main, "get_analytics_repository", lambda: repository)

    api_main._record_query_boundary(_request("/api/v1/query"), 422, "validation_error")
    api_main._record_query_boundary(_request("/api/v1/admin/users"), 403, "access_denied")

    assert len(repository._boundary_events) == 1
    event = next(iter(repository._boundary_events.values()))
    assert event.route_path == "/api/v1/query"
    assert event.status_code == 422
    assert event.reason_code == "validation_error"


def test_eligible_denial_is_not_also_counted_as_a_boundary_event(monkeypatch):
    repository = InMemoryAnalyticsRepository()
    monkeypatch.setattr(api_main, "get_analytics_repository", lambda: repository)
    request = _request("/api/v1/query/stream")
    request.state.query_analytics_recorded = True
    api_main._record_query_boundary(request, 403, "query_group_forbidden")
    assert not repository._boundary_events
