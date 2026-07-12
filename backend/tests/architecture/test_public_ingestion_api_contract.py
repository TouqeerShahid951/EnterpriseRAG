"""Regression contract for the public document and ingestion-job APIs."""

from collections.abc import Mapping
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any


OperationKey = tuple[str, str]
OperationContract = tuple[tuple[str, ...], frozenset[str]]

BACKEND_ROOT = Path(__file__).resolve().parents[2]

HTTP_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
)
PUBLIC_OPERATION_PREFIXES = ("/api/v1/docs", "/api/v1/ingest-jobs")

EXPECTED_OPERATIONS: dict[OperationKey, OperationContract] = {
    ("GET", "/api/v1/docs"): (("documents",), frozenset({"200", "422"})),
    ("GET", "/api/v1/docs/{document_id}"): (
        ("documents",),
        frozenset({"200", "404", "422"}),
    ),
    ("DELETE", "/api/v1/docs/{document_id}"): (
        ("documents",),
        frozenset({"200", "403", "404", "422"}),
    ),
    ("PATCH", "/api/v1/docs/{document_id}/clearance"): (
        ("documents",),
        frozenset({"200", "403", "404", "422", "502"}),
    ),
    ("GET", "/api/v1/docs/{document_id}/content"): (
        ("documents",),
        frozenset({"200", "206", "404", "422"}),
    ),
    ("POST", "/api/v1/docs/{document_id}/graph-enrichment"): (
        ("documents",),
        frozenset({"202", "403", "404", "409", "422", "503"}),
    ),
    ("GET", "/api/v1/docs/{document_id}/image-assets/{asset_id}/content"): (
        ("documents",),
        frozenset({"200", "404", "422"}),
    ),
    ("PATCH", "/api/v1/docs/{document_id}/owner"): (
        ("documents",),
        frozenset({"200", "403", "404", "409", "422", "502"}),
    ),
    ("DELETE", "/api/v1/docs/{document_id}/permanent"): (
        ("documents",),
        frozenset({"200", "403", "404", "422", "502"}),
    ),
    ("POST", "/api/v1/docs/{document_id}/reingest"): (
        ("documents",),
        frozenset({"202", "403", "404", "409", "422", "503"}),
    ),
    ("POST", "/api/v1/docs/{document_id}/restore"): (
        ("documents",),
        frozenset({"202", "403", "404", "409", "422", "503"}),
    ),
    ("GET", "/api/v1/docs/{document_id}/shares"): (
        ("documents",),
        frozenset({"200", "404", "422"}),
    ),
    ("PUT", "/api/v1/docs/{document_id}/shares"): (
        ("documents",),
        frozenset({"200", "403", "404", "422", "502"}),
    ),
    ("POST", "/api/v1/docs/{document_id}/shares/unshare"): (
        ("documents",),
        frozenset({"200", "403", "404", "422", "502"}),
    ),
    ("GET", "/api/v1/docs/{document_id}/sources/{chunk_id}"): (
        ("documents",),
        frozenset({"200", "404", "422", "502"}),
    ),
    ("POST", "/api/v1/docs/{document_id}/supersede"): (
        ("documents",),
        frozenset({"200", "400", "403", "404", "422"}),
    ),
    ("PATCH", "/api/v1/docs/{document_id}/topics"): (
        ("documents",),
        frozenset({"200", "403", "404", "422", "502"}),
    ),
    ("GET", "/api/v1/docs/{document_id}/versions"): (
        ("documents",),
        frozenset({"200", "404", "422"}),
    ),
    ("GET", "/api/v1/ingest-jobs"): (
        ("ingest-jobs",),
        frozenset({"200", "422"}),
    ),
    ("GET", "/api/v1/ingest-jobs/graphrag-status"): (
        ("ingest-jobs",),
        frozenset({"200"}),
    ),
    ("GET", "/api/v1/ingest-jobs/stale"): (
        ("ingest-jobs",),
        frozenset({"200"}),
    ),
    ("GET", "/api/v1/ingest-jobs/summary"): (
        ("ingest-jobs",),
        frozenset({"200", "422"}),
    ),
    ("POST", "/api/v1/ingest-jobs/{job_id}/cancel"): (
        ("ingest-jobs",),
        frozenset({"200", "422"}),
    ),
    ("POST", "/api/v1/ingest-jobs/{job_id}/graph-enrichment/cancel"): (
        ("ingest-jobs",),
        frozenset({"200", "403", "404", "409", "422", "503"}),
    ),
    ("POST", "/api/v1/ingest-jobs/{job_id}/requeue"): (
        ("ingest-jobs",),
        frozenset({"200", "422"}),
    ),
}


def test_public_document_and_ingest_job_openapi_contract() -> None:
    """Keep public operations stable regardless of their owning router module."""
    paths = _load_api_app().openapi()["paths"]

    assert _operation_contracts(paths) == EXPECTED_OPERATIONS


def _operation_contracts(
    paths: Mapping[str, Any],
) -> dict[OperationKey, OperationContract]:
    contracts: dict[OperationKey, OperationContract] = {}
    for path, path_item in paths.items():
        if not path.startswith(PUBLIC_OPERATION_PREFIXES):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            contracts[(method.upper(), path)] = (
                tuple(operation.get("tags", ())),
                frozenset(operation.get("responses", ())),
            )
    return contracts


def _load_api_app() -> Any:
    module_path = BACKEND_ROOT / "apps" / "api" / "main.py"
    spec = spec_from_file_location("agenticrag_api_main", module_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app
