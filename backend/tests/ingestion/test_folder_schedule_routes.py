from __future__ import annotations

from fastapi import HTTPException
from fastapi.routing import APIRoute
import pytest

from rag.ingestion.folders.errors import FolderIngestionRejected
from rag.ingestion.folders.routes import _raise_folder_http_error, router


EXPECTED_ROUTES = {
    ("GET", "/folder-ingest/local-folders"),
    ("GET", "/folder-ingest/schedules"),
    ("GET", "/folder-ingest/schedules/{schedule_id}"),
    ("POST", "/folder-ingest/schedules/snapshot"),
    ("POST", "/folder-ingest/schedules/minio-prefix"),
    ("POST", "/folder-ingest/schedules/local-folder"),
    ("POST", "/folder-ingest/schedules/connector"),
    ("PATCH", "/folder-ingest/schedules/{schedule_id}"),
    ("POST", "/folder-ingest/schedules/{schedule_id}/pause"),
    ("POST", "/folder-ingest/schedules/{schedule_id}/resume"),
    ("POST", "/folder-ingest/schedules/{schedule_id}/cancel"),
    ("GET", "/folder-ingest/schedules/{schedule_id}/runs"),
    ("GET", "/folder-ingest/runs/{run_id}/items"),
}


def _routes_by_method_and_path() -> dict[tuple[str, str], APIRoute]:
    return {
        (method, route.path): route
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_folder_ingestion_router_owns_the_existing_http_contract() -> None:
    routes = _routes_by_method_and_path()

    assert set(routes) == EXPECTED_ROUTES
    assert all(route.tags == ["folder-ingest"] for route in routes.values())


def test_folder_ingestion_mutation_status_codes_remain_stable() -> None:
    routes = _routes_by_method_and_path()

    assert routes[("POST", "/folder-ingest/schedules/snapshot")].status_code == 202
    assert routes[("POST", "/folder-ingest/schedules/minio-prefix")].status_code == 202
    assert routes[("POST", "/folder-ingest/schedules/local-folder")].status_code == 202
    assert routes[("POST", "/folder-ingest/schedules/connector")].status_code == 410
    assert (
        routes[("PATCH", "/folder-ingest/schedules/{schedule_id}")].status_code is None
    )
    assert (
        routes[("POST", "/folder-ingest/schedules/{schedule_id}/pause")].status_code
        is None
    )
    assert (
        routes[("POST", "/folder-ingest/schedules/{schedule_id}/resume")].status_code
        is None
    )
    assert (
        routes[("POST", "/folder-ingest/schedules/{schedule_id}/cancel")].status_code
        is None
    )


@pytest.mark.parametrize(
    ("category", "expected_status"),
    [
        ("invalid", 400),
        ("forbidden", 403),
        ("not_found", 404),
        ("too_large", 413),
        ("unavailable", 503),
    ],
)
def test_folder_ingestion_rejections_are_mapped_at_the_http_boundary(
    category: str,
    expected_status: int,
) -> None:
    rejection = FolderIngestionRejected(
        category=category,  # type: ignore[arg-type]
        code="safe_code",
        message="Safe detail.",
    )

    with pytest.raises(HTTPException) as exc_info:
        _raise_folder_http_error(rejection)

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == {"code": "safe_code", "message": "Safe detail."}
