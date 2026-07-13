"""Regression contract for public generated-artifact APIs."""

from collections.abc import Mapping
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any


OperationKey = tuple[str, str]
OperationContract = tuple[
    tuple[str, ...],
    frozenset[str],
    str,
    str,
    str | None,
    str | None,
]
SchemaContract = tuple[frozenset[str], frozenset[str]]

BACKEND_ROOT = Path(__file__).resolve().parents[2]

HTTP_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
)
PUBLIC_OPERATION_PREFIXES = (
    "/api/v1/artifact-jobs",
    "/api/v1/query/artifacts",
)

EXPECTED_OPERATIONS: dict[OperationKey, OperationContract] = {
    ("GET", "/api/v1/query/artifacts/{artifact_id}/content"): (
        ("query",),
        frozenset({"200", "422"}),
        "get_generated_artifact_content_api_v1_query_artifacts__artifact_id__content_get",
        "Download a generated query artifact",
        None,
        None,
    ),
    ("GET", "/api/v1/artifact-jobs/{job_id}"): (
        ("artifact-jobs",),
        frozenset({"200", "422"}),
        "get_artifact_job_api_v1_artifact_jobs__job_id__get",
        "Get Artifact Job",
        None,
        "ArtifactJobDetail",
    ),
    ("POST", "/api/v1/artifact-jobs/{job_id}/clarifications"): (
        ("artifact-jobs",),
        frozenset({"200", "422"}),
        "clarify_artifact_job_api_v1_artifact_jobs__job_id__clarifications_post",
        "Clarify Artifact Job",
        "ArtifactClarificationRequest",
        "ArtifactJobMutationResponse",
    ),
    ("POST", "/api/v1/artifact-jobs/{job_id}/cancel"): (
        ("artifact-jobs",),
        frozenset({"200", "422"}),
        "cancel_artifact_job_api_v1_artifact_jobs__job_id__cancel_post",
        "Cancel Artifact Job",
        None,
        "ArtifactJobMutationResponse",
    ),
    ("POST", "/api/v1/artifact-jobs/{job_id}/retry"): (
        ("artifact-jobs",),
        frozenset({"200", "422"}),
        "retry_artifact_job_api_v1_artifact_jobs__job_id__retry_post",
        "Retry Artifact Job",
        None,
        "ArtifactJobMutationResponse",
    ),
}

_SUMMARY_FIELDS = frozenset(
    {
        "id",
        "status",
        "stage",
        "progress_pct",
        "stage_label",
        "stage_detail",
        "stage_progress",
        "requested_formats",
        "clarification_questions",
        "artifacts",
        "error_code",
        "error_message",
        "attempt_count",
        "max_attempts",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "last_heartbeat_at",
        "expires_at",
    }
)
_SUMMARY_REQUIRED = frozenset(
    {
        "id",
        "status",
        "stage",
        "progress_pct",
        "stage_label",
        "stage_detail",
        "requested_formats",
    }
)
EXPECTED_SCHEMAS: dict[str, SchemaContract] = {
    "GeneratedArtifact": (
        frozenset(
            {
                "id",
                "filename",
                "format",
                "content_type",
                "size_bytes",
                "download_url",
                "created_at",
            }
        ),
        frozenset(
            {
                "id",
                "filename",
                "format",
                "content_type",
                "size_bytes",
                "download_url",
            }
        ),
    ),
    "ArtifactJobStageProgress": (
        frozenset({"unit", "current", "total", "label"}),
        frozenset({"unit", "current", "total"}),
    ),
    "ArtifactJobSummary": (_SUMMARY_FIELDS, _SUMMARY_REQUIRED),
    "ArtifactStageTiming": (
        frozenset({"duration_ms", "started_at", "completed_at"}),
        frozenset({"duration_ms"}),
    ),
    "ArtifactJobDetail": (
        _SUMMARY_FIELDS
        | {
            "original_request",
            "group_path",
            "document_ids",
            "plan",
            "evidence_manifest",
            "content_specification",
            "validation_results",
            "stage_timings",
            "errors",
        },
        _SUMMARY_REQUIRED | {"original_request"},
    ),
    "ArtifactClarificationRequest": (
        frozenset({"answers"}),
        frozenset({"answers"}),
    ),
    "ArtifactJobMutationResponse": (
        frozenset({"job"}),
        frozenset({"job"}),
    ),
}


def test_public_artifact_openapi_contract() -> None:
    """Keep artifact paths and contracts stable across module ownership moves."""
    openapi = _load_api_app().openapi()

    assert _operation_contracts(openapi["paths"]) == EXPECTED_OPERATIONS
    schemas = openapi["components"]["schemas"]
    assert {
        name: (
            frozenset(schemas[name]["properties"]),
            frozenset(schemas[name].get("required", ())),
        )
        for name in EXPECTED_SCHEMAS
    } == EXPECTED_SCHEMAS

    clarification_answers = schemas["ArtifactClarificationRequest"]["properties"][
        "answers"
    ]
    assert clarification_answers["minProperties"] == 1
    assert clarification_answers["maxProperties"] == 5
    assert schemas["GeneratedArtifact"]["properties"]["format"]["enum"] == [
        "docx",
        "pptx",
        "pdf",
    ]
    assert schemas["ArtifactJobSummary"]["properties"]["status"]["enum"] == [
        "queued",
        "planning",
        "needs_input",
        "retrieving",
        "composing",
        "validating",
        "rendering",
        "complete",
        "partial",
        "failed",
        "cancelled",
    ]


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
                operation["operationId"],
                operation["summary"],
                _schema_name(
                    operation.get("requestBody", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                ),
                _schema_name(
                    operation["responses"]["200"]
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                ),
            )
    return contracts


def _schema_name(schema: Mapping[str, Any]) -> str | None:
    reference = schema.get("$ref")
    return str(reference).rsplit("/", maxsplit=1)[-1] if reference else None


def _load_api_app() -> Any:
    module_path = BACKEND_ROOT / "apps" / "api" / "main.py"
    spec = spec_from_file_location("agenticrag_api_main", module_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app
