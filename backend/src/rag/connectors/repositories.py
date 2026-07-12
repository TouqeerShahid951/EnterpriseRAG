"""Connector profile persistence."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol
from uuid import uuid4

from rag.core.config import settings
from rag.shared.persistence import PostgresConnectionMixin

from .models import ConnectorProfileRecord, ConnectorSchemaCatalogRecord, ConnectorSchemaSnapshot


class ConnectorProfileRepository(Protocol):
    def create_profile(self, **kwargs: Any) -> ConnectorProfileRecord: ...
    def list_profiles(self) -> list[ConnectorProfileRecord]: ...
    def get_profile(self, profile_id: str) -> ConnectorProfileRecord | None: ...
    def update_profile(self, profile_id: str, **kwargs: Any) -> ConnectorProfileRecord | None: ...
    def delete_profile(self, profile_id: str) -> bool: ...
    def record_test_result(self, profile_id: str, *, status: str, message: str) -> ConnectorProfileRecord | None: ...
    def save_introspection(self, *, profile_id: str, connector_type: str, schema_json: dict[str, Any], status: str, error_message_safe: str | None = None) -> ConnectorSchemaSnapshot: ...
    def latest_introspection(self, profile_id: str) -> ConnectorSchemaSnapshot | None: ...
    def save_schema_catalog(
        self,
        *,
        profile_id: str,
        connector_type: str,
        catalog_json: dict[str, Any],
        status: str,
        group_path: str,
        clearance_level: str,
        created_by: str | None = None,
        approved_by: str | None = None,
    ) -> ConnectorSchemaCatalogRecord: ...
    def list_schema_catalogs(self, profile_id: str | None = None) -> list[ConnectorSchemaCatalogRecord]: ...
    def get_schema_catalog(self, catalog_id: str) -> ConnectorSchemaCatalogRecord | None: ...
    def update_schema_catalog(self, catalog_id: str, **kwargs: Any) -> ConnectorSchemaCatalogRecord | None: ...


class InMemoryConnectorProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[str, ConnectorProfileRecord] = {}
        self._schemas: dict[str, list[ConnectorSchemaSnapshot]] = {}
        self._catalogs: dict[str, ConnectorSchemaCatalogRecord] = {}

    def create_profile(self, **kwargs: Any) -> ConnectorProfileRecord:
        now = datetime.now(UTC)
        record = ConnectorProfileRecord(
            id=kwargs.get("profile_id") or str(uuid4()),
            name=str(kwargs["name"]).strip(),
            connector_type=str(kwargs["connector_type"]),
            public_config=dict(kwargs.get("public_config") or {}),
            encrypted_secrets=str(kwargs["encrypted_secrets"]),
            created_by=kwargs.get("created_by"),
            last_test_status=None,
            last_test_message=None,
            last_tested_at=None,
            created_at=now,
            updated_at=now,
        )
        self._profiles[record.id] = record
        return record

    def list_profiles(self) -> list[ConnectorProfileRecord]:
        return sorted(self._profiles.values(), key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    def get_profile(self, profile_id: str) -> ConnectorProfileRecord | None:
        return self._profiles.get(profile_id)

    def update_profile(self, profile_id: str, **kwargs: Any) -> ConnectorProfileRecord | None:
        record = self._profiles.get(profile_id)
        if record is None:
            return None
        updated = replace(
            record,
            name=str(kwargs.get("name", record.name)).strip(),
            public_config=dict(kwargs.get("public_config", record.public_config)),
            encrypted_secrets=str(kwargs.get("encrypted_secrets", record.encrypted_secrets)),
            updated_at=datetime.now(UTC),
        )
        self._profiles[profile_id] = updated
        return updated

    def delete_profile(self, profile_id: str) -> bool:
        return self._profiles.pop(profile_id, None) is not None

    def record_test_result(self, profile_id: str, *, status: str, message: str) -> ConnectorProfileRecord | None:
        record = self._profiles.get(profile_id)
        if record is None:
            return None
        updated = replace(record, last_test_status=status, last_test_message=message, last_tested_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        self._profiles[profile_id] = updated
        return updated

    def save_introspection(self, *, profile_id: str, connector_type: str, schema_json: dict[str, Any], status: str, error_message_safe: str | None = None) -> ConnectorSchemaSnapshot:
        snapshot = ConnectorSchemaSnapshot(
            id=str(uuid4()),
            profile_id=profile_id,
            connector_type=connector_type,
            schema_json=dict(schema_json),
            status=status,
            error_message_safe=error_message_safe,
            created_at=datetime.now(UTC),
        )
        self._schemas.setdefault(profile_id, []).append(snapshot)
        return snapshot

    def latest_introspection(self, profile_id: str) -> ConnectorSchemaSnapshot | None:
        snapshots = self._schemas.get(profile_id, [])
        return sorted(snapshots, key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)[0] if snapshots else None

    def save_schema_catalog(
        self,
        *,
        profile_id: str,
        connector_type: str,
        catalog_json: dict[str, Any],
        status: str,
        group_path: str,
        clearance_level: str,
        created_by: str | None = None,
        approved_by: str | None = None,
    ) -> ConnectorSchemaCatalogRecord:
        now = datetime.now(UTC)
        record = ConnectorSchemaCatalogRecord(
            id=str(uuid4()),
            profile_id=profile_id,
            connector_type=connector_type,
            status=status,
            group_path=group_path,
            clearance_level=clearance_level,
            catalog_json=dict(catalog_json),
            created_by=created_by,
            approved_by=approved_by,
            created_at=now,
            updated_at=now,
        )
        self._catalogs[record.id] = record
        return record

    def list_schema_catalogs(self, profile_id: str | None = None) -> list[ConnectorSchemaCatalogRecord]:
        catalogs = [item for item in self._catalogs.values() if profile_id is None or item.profile_id == profile_id]
        return sorted(catalogs, key=lambda item: item.updated_at or item.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    def get_schema_catalog(self, catalog_id: str) -> ConnectorSchemaCatalogRecord | None:
        return self._catalogs.get(catalog_id)

    def update_schema_catalog(self, catalog_id: str, **kwargs: Any) -> ConnectorSchemaCatalogRecord | None:
        record = self._catalogs.get(catalog_id)
        if record is None:
            return None
        updated = replace(
            record,
            status=str(kwargs["status"]) if kwargs.get("status") is not None else record.status,
            group_path=str(kwargs["group_path"]) if kwargs.get("group_path") is not None else record.group_path,
            clearance_level=str(kwargs["clearance_level"]) if kwargs.get("clearance_level") is not None else record.clearance_level,
            catalog_json=dict(kwargs.get("catalog_json", record.catalog_json)),
            approved_by=kwargs["approved_by"] if "approved_by" in kwargs else record.approved_by,
            updated_at=datetime.now(UTC),
        )
        self._catalogs[catalog_id] = updated
        return updated


class PostgresConnectorProfileRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create_profile(self, **kwargs: Any) -> ConnectorProfileRecord:
        row = self._execute_one(
            """
            INSERT INTO connector_profiles (name, connector_type, public_config, encrypted_secrets, created_by)
            VALUES (%s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (
                str(kwargs["name"]).strip(),
                kwargs["connector_type"],
                json.dumps(kwargs.get("public_config") or {}),
                kwargs["encrypted_secrets"],
                kwargs.get("created_by"),
            ),
        )
        return profile_from_row(row)

    def list_profiles(self) -> list[ConnectorProfileRecord]:
        rows = self._execute_all("SELECT * FROM connector_profiles ORDER BY created_at DESC, id DESC")
        return [profile_from_row(row) for row in rows]

    def get_profile(self, profile_id: str) -> ConnectorProfileRecord | None:
        row = self._execute_optional("SELECT * FROM connector_profiles WHERE id = %s", (profile_id,))
        return profile_from_row(row) if row else None

    def update_profile(self, profile_id: str, **kwargs: Any) -> ConnectorProfileRecord | None:
        row = self._execute_optional(
            """
            UPDATE connector_profiles
            SET name = COALESCE(%s, name),
                public_config = COALESCE(%s::jsonb, public_config),
                encrypted_secrets = COALESCE(%s, encrypted_secrets),
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                str(kwargs["name"]).strip() if kwargs.get("name") is not None else None,
                json.dumps(kwargs["public_config"]) if kwargs.get("public_config") is not None else None,
                kwargs.get("encrypted_secrets"),
                profile_id,
            ),
        )
        return profile_from_row(row) if row else None

    def delete_profile(self, profile_id: str) -> bool:
        row = self._execute_optional("DELETE FROM connector_profiles WHERE id = %s RETURNING id", (profile_id,))
        return row is not None

    def record_test_result(self, profile_id: str, *, status: str, message: str) -> ConnectorProfileRecord | None:
        row = self._execute_optional(
            """
            UPDATE connector_profiles
            SET last_test_status = %s, last_test_message = %s, last_tested_at = NOW(), updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (status, message[:500], profile_id),
        )
        return profile_from_row(row) if row else None

    def save_introspection(self, *, profile_id: str, connector_type: str, schema_json: dict[str, Any], status: str, error_message_safe: str | None = None) -> ConnectorSchemaSnapshot:
        row = self._execute_one(
            """
            INSERT INTO connector_schema_snapshots (profile_id, connector_type, schema_json, status, error_message_safe)
            VALUES (%s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (profile_id, connector_type, json.dumps(schema_json), status, error_message_safe[:500] if error_message_safe else None),
        )
        return schema_from_row(row)

    def latest_introspection(self, profile_id: str) -> ConnectorSchemaSnapshot | None:
        row = self._execute_optional(
            """
            SELECT * FROM connector_schema_snapshots
            WHERE profile_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (profile_id,),
        )
        return schema_from_row(row) if row else None

    def save_schema_catalog(
        self,
        *,
        profile_id: str,
        connector_type: str,
        catalog_json: dict[str, Any],
        status: str,
        group_path: str,
        clearance_level: str,
        created_by: str | None = None,
        approved_by: str | None = None,
    ) -> ConnectorSchemaCatalogRecord:
        row = self._execute_one(
            """
            INSERT INTO connector_schema_catalogs (
                profile_id, connector_type, status, group_path, clearance_level,
                catalog_json, created_by, approved_by
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (profile_id, connector_type, status, group_path, clearance_level, json.dumps(catalog_json), created_by, approved_by),
        )
        return catalog_from_row(row)

    def list_schema_catalogs(self, profile_id: str | None = None) -> list[ConnectorSchemaCatalogRecord]:
        if profile_id is not None:
            rows = self._execute_all(
                """
                SELECT * FROM connector_schema_catalogs
                WHERE profile_id = %s
                ORDER BY updated_at DESC, created_at DESC, id DESC
                """,
                (profile_id,),
            )
        else:
            rows = self._execute_all("SELECT * FROM connector_schema_catalogs ORDER BY updated_at DESC, created_at DESC, id DESC")
        return [catalog_from_row(row) for row in rows]

    def get_schema_catalog(self, catalog_id: str) -> ConnectorSchemaCatalogRecord | None:
        row = self._execute_optional("SELECT * FROM connector_schema_catalogs WHERE id = %s", (catalog_id,))
        return catalog_from_row(row) if row else None

    def update_schema_catalog(self, catalog_id: str, **kwargs: Any) -> ConnectorSchemaCatalogRecord | None:
        approved_by_provided = "approved_by" in kwargs
        row = self._execute_optional(
            """
            UPDATE connector_schema_catalogs
            SET status = COALESCE(%s, status),
                group_path = COALESCE(%s, group_path),
                clearance_level = COALESCE(%s, clearance_level),
                catalog_json = COALESCE(%s::jsonb, catalog_json),
                approved_by = CASE WHEN %s THEN %s ELSE approved_by END,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                kwargs.get("status"),
                kwargs.get("group_path"),
                kwargs.get("clearance_level"),
                json.dumps(kwargs["catalog_json"]) if kwargs.get("catalog_json") is not None else None,
                approved_by_provided,
                kwargs.get("approved_by"),
                catalog_id,
            ),
        )
        return catalog_from_row(row) if row else None


def profile_from_row(row: dict[str, Any]) -> ConnectorProfileRecord:
    return ConnectorProfileRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        connector_type=str(row["connector_type"]),
        public_config=_json_object(row.get("public_config")),
        encrypted_secrets=str(row["encrypted_secrets"]),
        created_by=str(row["created_by"]) if row.get("created_by") else None,
        last_test_status=row.get("last_test_status"),
        last_test_message=row.get("last_test_message"),
        last_tested_at=row.get("last_tested_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def schema_from_row(row: dict[str, Any]) -> ConnectorSchemaSnapshot:
    return ConnectorSchemaSnapshot(
        id=str(row["id"]),
        profile_id=str(row["profile_id"]),
        connector_type=str(row["connector_type"]),
        schema_json=_json_object(row.get("schema_json")),
        status=str(row["status"]),
        error_message_safe=row.get("error_message_safe"),
        created_at=row.get("created_at"),
    )


def catalog_from_row(row: dict[str, Any]) -> ConnectorSchemaCatalogRecord:
    return ConnectorSchemaCatalogRecord(
        id=str(row["id"]),
        profile_id=str(row["profile_id"]),
        connector_type=str(row["connector_type"]),
        status=str(row["status"]),
        group_path=str(row["group_path"]),
        clearance_level=str(row["clearance_level"]),
        catalog_json=_json_object(row.get("catalog_json")),
        created_by=str(row["created_by"]) if row.get("created_by") else None,
        approved_by=str(row["approved_by"]) if row.get("approved_by") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


@lru_cache
def default_connector_profile_repository() -> ConnectorProfileRepository:
    if settings.document_repository == "memory":
        return InMemoryConnectorProfileRepository()
    return PostgresConnectorProfileRepository(settings.database_url)


def get_connector_profile_repository() -> ConnectorProfileRepository:
    return default_connector_profile_repository()
