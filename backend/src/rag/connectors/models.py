"""Connector records and constants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

CONNECTOR_RECORD_CONTENT_TYPE = "application/vnd.agenticrag.connector-record+json"
JSON_SNAPSHOT_MODE = "json_snapshot"
DIRECT_CHUNKS_MODE = "direct_chunks"

ConnectorType = Literal[
    "sql_server",
    "postgres",
    "mysql",
    "mariadb",
    "mongodb",
    "oracle",
    "opensearch",
    "elasticsearch",
    "redis",
    "cassandra",
    "fake",
]

IngestionMode = Literal["json_snapshot", "direct_chunks"]
ConnectorSchemaCatalogStatus = Literal["draft", "reviewed", "approved", "disabled"]
DeletionPolicy = Literal[
    "keep_deleted_documents",
    "mark_as_stale",
    "archive_from_retrieval",
    "delete_from_index_after_review",
]


@dataclass(frozen=True)
class ConnectorProfileRecord:
    id: str
    name: str
    connector_type: str
    public_config: dict[str, Any]
    encrypted_secrets: str
    created_by: str | None
    last_test_status: str | None
    last_test_message: str | None
    last_tested_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ConnectorSchemaSnapshot:
    id: str
    profile_id: str
    connector_type: str
    schema_json: dict[str, Any]
    status: str
    error_message_safe: str | None
    created_at: datetime | None


@dataclass(frozen=True)
class ConnectorSchemaCatalogRecord:
    id: str
    profile_id: str
    connector_type: str
    status: str
    group_path: str
    clearance_level: str
    catalog_json: dict[str, Any]
    created_by: str | None
    approved_by: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ConnectorRecord:
    source_path: str
    title: str
    data: dict[str, Any]
    identity: dict[str, Any]
    updated_at: str | None = None


@dataclass(frozen=True)
class ConnectorTestResult:
    status: str
    message: str
    detail: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConnectorQueryResult:
    query: str
    columns: list[str]
    rows: list[dict[str, Any]]
