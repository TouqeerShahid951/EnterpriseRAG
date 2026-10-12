"""Regression contract for public query HTTP operations."""

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
PUBLIC_QUERY_PATHS = (
    "/api/v1/query/sessions",
    "/api/v1/query/sources",
    "/api/v1/query/sessions/{session_id}",
    "/api/v1/query",
    "/api/v1/query/stream",
)

EXPECTED_OPERATIONS: dict[OperationKey, OperationContract] = {
    ("GET", "/api/v1/query/sessions"): (
        ("query",),
        frozenset({"200", "422"}),
        "list_chat_sessions_api_v1_query_sessions_get",
        "List saved chat sessions for the current permission version",
        None,
        "ChatSessionListResponse",
    ),
    ("GET", "/api/v1/query/sources"): (
        ("query",),
        frozenset({"200", "422"}),
        "list_query_sources_api_v1_query_sources_get",
        "List visible approved query sources for source-scoped chat",
        None,
        "QuerySourceListResponse",
    ),
    ("GET", "/api/v1/query/sessions/{session_id}"): (
        ("query",),
        frozenset({"200", "422"}),
        "get_chat_session_api_v1_query_sessions__session_id__get",
        "Read a saved chat session",
        None,
        "ChatSession",
    ),
    ("DELETE", "/api/v1/query/sessions/{session_id}"): (
        ("query",),
        frozenset({"204", "422"}),
        "delete_chat_session_api_v1_query_sessions__session_id__delete",
        "Delete a saved chat session",
        None,
        None,
    ),
    ("POST", "/api/v1/query"): (
        ("query",),
        frozenset({"200", "422"}),
        "run_query_api_v1_query_post",
        "Run a retrieval-augmented query",
        "QueryRequest",
        "RAGResponse",
    ),
    ("POST", "/api/v1/query/stream"): (
        ("query",),
        frozenset({"200", "422"}),
        "stream_query_api_v1_query_stream_post",
        "Run a streaming retrieval-augmented query",
        "QueryRequest",
        None,
    ),
}

EXPECTED_SCHEMAS: dict[str, SchemaContract] = {
    "QueryRequest": (
        frozenset(
            {
                "query",
                "session_id",
                "client_request_id",
                "reply_to_turn_id",
                "group_path",
                "document_ids",
                "source_mode",
                "query_source_id",
                "query_source_ids",
                "allow_source_expansion",
                "continue_source_clarification",
            }
        ),
        frozenset({"query"}),
    ),
    "QuerySource": (
        frozenset(
            {
                "id",
                "kind",
                "name",
                "description",
                "connector_type",
                "scope",
                "group_path",
                "clearance_level",
            }
        ),
        frozenset({"id", "kind", "name", "connector_type", "scope", "group_path"}),
    ),
    "QuerySourceListResponse": (
        frozenset({"items", "total"}),
        frozenset({"total"}),
    ),
    "RAGResponse": (
        frozenset(['answer', 'answer_status', 'artifact_job', 'artifacts', 'citation_verification', 'conflict_detail', 'conflict_flag', 'coverage', 'degraded', 'degraded_reason', 'faithfulness_score', 'faithfulness_status', 'intent', 'latency_ms', 'node_timings', 'operational_failures', 'query_source_id', 'session_id', 'source_clarification', 'source_decision_reason', 'source_expansion', 'source_mode', 'sources', 'trace_id', 'unfounded_claims']),
        frozenset(['answer', 'conflict_flag', 'degraded', 'faithfulness_score', 'intent', 'latency_ms', 'session_id', 'trace_id']),
    ),
    "QueryCoverage": (
        frozenset(
            {
                "required_slots",
                "covered_slots",
                "completeness",
                "warnings",
            }
        ),
        frozenset(),
    ),
    "QueryOperationalFailure": (
        frozenset({"stage", "code", "retryable", "source_id", "message"}),
        frozenset({"stage", "code", "retryable", "message"}),
    ),
    "ChatSession": (
        frozenset({"id", "title", "created_at", "updated_at", "turns"}),
        frozenset({"id", "title", "created_at", "updated_at"}),
    ),
    "ChatSessionSummary": (
        frozenset({"id", "title", "created_at", "updated_at", "question_count"}),
        frozenset({"id", "title", "created_at", "updated_at"}),
    ),
    "ChatSessionListResponse": (
        frozenset({"items", "total", "limit", "offset"}),
        frozenset({"items", "total", "limit", "offset"}),
    ),
    "HighlightRange": (
        frozenset({"start", "end"}),
        frozenset({"start", "end"}),
    ),
    "TextCitationTarget": (
        frozenset(['exact_text', 'kind', 'occurrence', 'prefix', 'provenance_kind', 'suffix']),
        frozenset(['exact_text']),
    ),
    "PageCitationTarget": (
        frozenset(['bbox', 'confidence', 'exact_text', 'extraction_method', 'image_asset_id', 'image_source_kind', 'kind', 'page', 'provenance_kind', 'region_type']),
        frozenset(['bbox', 'page']),
    ),
    "SlideCitationTarget": (
        frozenset(['bbox', 'confidence', 'exact_text', 'extraction_method', 'image_asset_id', 'image_source_kind', 'kind', 'page', 'provenance_kind', 'region_type']),
        frozenset(['bbox', 'page']),
    ),
    "ImageCitationTarget": (
        frozenset(['bbox', 'confidence', 'exact_text', 'extraction_method', 'image_asset_id', 'image_source_kind', 'kind', 'provenance_kind']),
        frozenset([]),
    ),
    "SpreadsheetCitationTarget": (
        frozenset(['end_column', 'end_row', 'exact_text', 'kind', 'provenance_kind', 'sheet_name', 'start_column', 'start_row']),
        frozenset(['end_column', 'end_row', 'sheet_name', 'start_column', 'start_row']),
    ),
    "JsonCitationTarget": (
        frozenset(['exact_text', 'kind', 'pointer', 'provenance_kind']),
        frozenset(['pointer']),
    ),
    "RecordCitationTarget": (
        frozenset(['exact_text', 'fields', 'kind', 'provenance_kind', 'record_id']),
        frozenset(['record_id']),
    ),
    "EvidenceField": (
        frozenset({"label", "value", "supports_claim"}),
        frozenset({"label", "value"}),
    ),
    "EvidenceWindow": (
        frozenset(
            {
                "claim_id",
                "claim",
                "kind",
                "passage",
                "highlight_ranges",
                "support_status",
                "support_score",
                "source_start",
                "source_end",
                "quote_start",
                "quote_end",
                "truncated_start",
                "truncated_end",
                "table_title",
                "fields",
            }
        ),
        frozenset(
            {
                "claim_id",
                "claim",
                "passage",
                "support_status",
                "support_score",
                "source_start",
                "source_end",
            }
        ),
    ),
    "SourceAnchor-Output": (
        frozenset(['attribution_status', 'chunk_id', 'citation_protocol_version', 'citation_targets', 'clearance_level', 'content_hash', 'doc_id', 'doc_title', 'effective_date', 'evidence_hash', 'evidence_windows', 'excerpt', 'group_path', 'highlight_ranges', 'index_generation_id', 'page', 'page_end', 'page_start', 'provenance_kind']),
        frozenset(['chunk_id', 'doc_id', 'doc_title', 'excerpt', 'group_path']),
    ),
    "ConflictPair-Output": (
        frozenset(
            {
                "claim_a_id",
                "claim_b_id",
                "doc_a_id",
                "doc_b_id",
                "chunk_a_id",
                "chunk_b_id",
                "entity",
                "attribute",
                "value_a",
                "value_b",
                "effective_date_a",
                "effective_date_b",
                "source_a",
                "source_b",
            }
        ),
        frozenset(
            {
                "claim_a_id",
                "claim_b_id",
                "doc_a_id",
                "doc_b_id",
                "chunk_a_id",
                "chunk_b_id",
                "entity",
                "attribute",
                "value_a",
                "value_b",
                "source_a",
                "source_b",
            }
        ),
    ),
    "SourceExpansion": (
        frozenset({"available", "reason", "suggested_source_mode"}),
        frozenset({"reason"}),
    ),
    "QuerySourceClarification": (
        frozenset({"question", "options"}),
        frozenset({"question"}),
    ),
    "QuerySourceClarificationOption": (
        frozenset({"source_id", "name", "description"}),
        frozenset({"source_id", "name"}),
    ),
    "QueryNodeTiming": (
        frozenset(
            {
                "node",
                "duration_ms",
                "execution_mode",
                "detail",
                "phase_timings_ms",
            }
        ),
        frozenset({"node", "duration_ms"}),
    ),
}


EXPECTED_SCHEMAS.update({
    'EvidenceQuote': (frozenset(['source_end', 'source_label', 'source_start', 'text']), frozenset(['source_end', 'source_label', 'source_start', 'text'])),
    'CitationClaim': (frozenset(['answer_end', 'answer_start', 'claim_id', 'quotes', 'reason', 'source_labels', 'text', 'verdict']), frozenset(['answer_end', 'answer_start', 'claim_id', 'text'])),
    'CitationVerification': (frozenset(['answer_sha256', 'claims', 'offset_unit', 'repair_count', 'status', 'version']), frozenset(['answer_sha256', 'status'])),
})

def test_public_query_openapi_contract() -> None:
    """Keep query paths and contracts stable across feature ownership moves."""
    openapi = _load_api_app().openapi()
    paths = openapi["paths"]

    assert (
        tuple(
            path
            for path in paths
            if path.startswith("/api/v1/query")
            and not path.startswith("/api/v1/query/artifacts")
        )
        == PUBLIC_QUERY_PATHS
    )
    assert _operation_contracts(paths) == EXPECTED_OPERATIONS
    schemas = openapi["components"]["schemas"]
    assert {"source_matched", "unverified", "verified"} <= set(
        schemas["CitationVerification"]["properties"]["status"]["enum"]
    )
    assert "source_matched" in schemas["EvidenceWindow"]["properties"]["support_status"]["enum"]
    assert {
        name: (
            frozenset(schemas[name]["properties"]),
            frozenset(schemas[name].get("required", ())),
        )
        for name in EXPECTED_SCHEMAS
    } == EXPECTED_SCHEMAS

    query_request = schemas["QueryRequest"]["properties"]
    assert query_request["query"]["minLength"] == 1
    assert query_request["document_ids"]["maxItems"] == 20
    assert query_request["client_request_id"]["anyOf"][0] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 120,
    }
    assert query_request["reply_to_turn_id"]["anyOf"][0] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 160,
    }
    assert query_request["query_source_id"]["anyOf"][0] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 240,
    }
    assert query_request["query_source_ids"]["maxItems"] == 3
    assert query_request["source_mode"]["enum"] == [
        "auto",
        "corpus_only",
        "db_only",
        "hybrid",
    ]
    assert query_request["source_mode"]["default"] == "auto"

    rag_response = schemas["RAGResponse"]["properties"]
    assert rag_response["intent"]["enum"] == [
        "factual_simple",
        "multi_hop",
        "temporal",
        "contradictory",
        "aggregation",
        "conversational",
    ]
    assert rag_response["faithfulness_status"]["enum"] == [
        "pending",
        "checked",
        "skipped",
        "failed",
    ]
    assert rag_response["faithfulness_score"]["minimum"] == 0
    assert rag_response["faithfulness_score"]["maximum"] == 1
    assert rag_response["answer_status"]["enum"] == [
        "complete",
        "partial",
        "clarification",
        "abstained",
    ]
    assert schemas["QueryCoverage"]["properties"]["completeness"]["enum"] == [
        "complete",
        "partial",
        "unknown",
        "not_applicable",
    ]

    session_parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in paths["/api/v1/query/sessions"]["get"]["parameters"]
    }
    assert session_parameters["limit"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 30,
        "title": "Limit",
    }
    assert session_parameters["offset"] == {
        "type": "integer",
        "minimum": 0,
        "default": 0,
        "title": "Offset",
    }


def _operation_contracts(
    paths: Mapping[str, Any],
) -> dict[OperationKey, OperationContract]:
    contracts: dict[OperationKey, OperationContract] = {}
    for path in PUBLIC_QUERY_PATHS:
        for method, operation in paths[path].items():
            if method not in HTTP_METHODS:
                continue
            success_response = next(
                response
                for status_code, response in sorted(operation["responses"].items())
                if status_code.startswith("2")
            )
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
                    success_response.get("content", {})
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
