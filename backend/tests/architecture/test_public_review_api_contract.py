"""Regression contract for the public Review Queue summary API."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_public_review_summary_openapi_contract() -> None:
    openapi = _load_api_app().openapi()
    operation = openapi["paths"]["/api/v1/review-queue/summary"]["get"]

    assert operation["tags"] == ["review-queue"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReviewQueueSummaryResponse"
    }
    schema = openapi["components"]["schemas"]["ReviewQueueSummaryResponse"]
    assert set(schema["properties"]) == {"pending_document_count"}
    assert set(schema["required"]) == {"pending_document_count"}


def _load_api_app() -> Any:
    module_path = BACKEND_ROOT / "apps" / "api" / "main.py"
    spec = spec_from_file_location("agenticrag_api_main", module_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app
