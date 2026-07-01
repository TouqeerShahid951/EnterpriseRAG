"""Public connector profile schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .common import ContractModel

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


class ConnectorProfileCreateRequest(ContractModel):
    name: str = Field(..., min_length=1, max_length=200)
    connector_type: ConnectorType
    public_config: dict[str, object] = Field(default_factory=dict)
    secrets: dict[str, object] = Field(default_factory=dict)


class ConnectorProfileUpdateRequest(ContractModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    public_config: dict[str, object] | None = None
    secrets: dict[str, object] | None = None


class ConnectorProfile(ContractModel):
    id: str
    name: str
    connector_type: ConnectorType | str
    public_config: dict[str, object] = Field(default_factory=dict)
    secrets_redacted: dict[str, str] = Field(default_factory=dict)
    created_by: str | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_tested_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConnectorProfileListResponse(ContractModel):
    items: list[ConnectorProfile] = Field(default_factory=list)
    total: int = Field(..., ge=0)


ConnectorSchemaCatalogStatus = Literal["draft", "reviewed", "approved", "disabled"]


class ConnectorSchemaCatalogCreateRequest(ContractModel):
    catalog_json: dict[str, object] | None = None
    status: ConnectorSchemaCatalogStatus = "draft"
    group_path: str = Field(..., min_length=1, max_length=300)
    group_paths: list[str] = Field(default_factory=list, max_length=128)
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL


class ConnectorSchemaCatalogAiDraftRequest(ContractModel):
    group_path: str = Field(..., min_length=1, max_length=300)
    group_paths: list[str] = Field(default_factory=list, max_length=128)
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL


class ConnectorSchemaCatalogTableEnrichRequest(ContractModel):
    table_key: str = Field(..., min_length=1, max_length=500)


class ConnectorSchemaCatalogUpdateRequest(ContractModel):
    catalog_json: dict[str, object] | None = None
    status: ConnectorSchemaCatalogStatus | None = None
    group_path: str | None = Field(default=None, min_length=1, max_length=300)
    group_paths: list[str] | None = Field(default=None, max_length=128)
    clearance_level: ClearanceLevel | None = None


class ConnectorSchemaCatalog(ContractModel):
    id: str
    profile_id: str
    connector_type: str
    status: ConnectorSchemaCatalogStatus | str
    group_path: str
    owner_group_path: str
    shared_group_paths: list[str] = Field(default_factory=list)
    access_group_paths: list[str] = Field(default_factory=list)
    clearance_level: ClearanceLevel | str
    catalog_json: dict[str, object] = Field(default_factory=dict)
    created_by: str | None = None
    approved_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConnectorSchemaCatalogListResponse(ContractModel):
    items: list[ConnectorSchemaCatalog] = Field(default_factory=list)
    total: int = Field(..., ge=0)


class ConnectorTestResponse(ContractModel):
    status: Literal["ok", "failed"]
    message: str
    detail: dict[str, object] = Field(default_factory=dict)
    profile: ConnectorProfile | None = None


class ConnectorSchemaSnapshot(ContractModel):
    id: str
    profile_id: str
    connector_type: str
    schema_payload: dict[str, object] = Field(default_factory=dict, alias="schema_json")
    status: Literal["ok", "failed"]
    error_message: str | None = None
    created_at: datetime | None = None
