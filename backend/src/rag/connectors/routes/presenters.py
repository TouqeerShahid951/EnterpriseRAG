"""HTTP response mapping for connector records."""

from __future__ import annotations

from rag.connectors.schemas import (
    ConnectorProfile,
    ConnectorSchemaCatalog,
    ConnectorSchemaSnapshot,
)
from rag.connectors.crypto import redact_secrets
from rag.connectors.models import (
    ConnectorProfileRecord,
    ConnectorSchemaCatalogRecord,
    ConnectorSchemaSnapshot as ConnectorSchemaSnapshotRecord,
)
from rag.connectors.catalog.schema_catalog import (
    schema_catalog_access_group_paths,
    schema_catalog_shared_group_paths,
)
from .support import secrets


def profile_to_schema(profile: ConnectorProfileRecord) -> ConnectorProfile:
    redacted = redact_secrets(secrets(profile.encrypted_secrets))
    return ConnectorProfile(
        id=profile.id,
        name=profile.name,
        connector_type=profile.connector_type,
        public_config=dict(profile.public_config),
        secrets_redacted=redacted,
        created_by=profile.created_by,
        last_test_status=profile.last_test_status,
        last_test_message=profile.last_test_message,
        last_tested_at=profile.last_tested_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def schema_to_response(
    snapshot: ConnectorSchemaSnapshotRecord,
) -> ConnectorSchemaSnapshot:
    return ConnectorSchemaSnapshot(
        id=snapshot.id,
        profile_id=snapshot.profile_id,
        connector_type=snapshot.connector_type,
        schema_json=dict(snapshot.schema_json),
        status=snapshot.status,
        error_message=snapshot.error_message_safe,
        created_at=snapshot.created_at,
    )


def catalog_to_schema(catalog: ConnectorSchemaCatalogRecord) -> ConnectorSchemaCatalog:
    shared_group_paths = schema_catalog_shared_group_paths(catalog.catalog_json)
    access_group_paths = schema_catalog_access_group_paths(
        catalog.group_path,
        catalog.catalog_json,
    )
    return ConnectorSchemaCatalog(
        id=catalog.id,
        profile_id=catalog.profile_id,
        connector_type=catalog.connector_type,
        status=catalog.status,
        group_path=catalog.group_path,
        owner_group_path=catalog.group_path,
        shared_group_paths=shared_group_paths,
        access_group_paths=access_group_paths,
        clearance_level=catalog.clearance_level,
        catalog_json=dict(catalog.catalog_json),
        created_by=catalog.created_by,
        approved_by=catalog.approved_by,
        created_at=catalog.created_at,
        updated_at=catalog.updated_at,
    )
