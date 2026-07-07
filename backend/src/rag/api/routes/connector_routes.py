"""Connector profile management routes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...auth.dependencies import require_csrf, require_current_user
from ...auth.permissions import can_manage_group_path, can_manage_spaces
from ...connectors.crypto import decrypt_secret, encrypt_secret, keyring_from_settings, redact_secrets
from ...connectors.repositories import ConnectorProfileRepository, get_connector_profile_repository
from ...connectors.registry import default_connector_registry
from ...connectors.schema_catalog import (
    build_default_schema_catalog,
    schema_catalog_access_group_paths,
    schema_catalog_shared_group_paths,
    schema_catalog_with_shared_group_paths,
)
from ...connectors.schema_enrichment import (
    SchemaEnrichmentError,
    enrich_schema_table_with_llm,
    initialize_schema_catalog_enrichment,
    schema_catalog_table_keys,
    schema_catalog_with_table_enrichment_failure,
)
from ...core.config import settings
from ...query.inference import build_inference_client
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...repositories.rag_config import effective_rag_config
from ...schemas.connectors import (
    ConnectorSchemaCatalog,
    ConnectorSchemaCatalogAiDraftRequest,
    ConnectorSchemaCatalogCreateRequest,
    ConnectorSchemaCatalogListResponse,
    ConnectorSchemaCatalogTableEnrichRequest,
    ConnectorSchemaCatalogUpdateRequest,
    ConnectorProfile,
    ConnectorProfileCreateRequest,
    ConnectorProfileListResponse,
    ConnectorProfileUpdateRequest,
    ConnectorSchemaSnapshot,
    ConnectorTestResponse,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchemaEnrichmentRuntime:
    llm: object
    model: str | None


def get_schema_enrichment_runtime() -> SchemaEnrichmentRuntime:
    rag_config = effective_rag_config(config=settings)
    return SchemaEnrichmentRuntime(
        llm=build_inference_client(rag_config, settings=settings),
        model=rag_config.effective_reasoning_model or rag_config.chat_model,
    )


@router.get("/profiles", response_model=ConnectorProfileListResponse, summary="List connector profiles")
def list_connector_profiles(
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorProfileListResponse:
    _require_connector_admin(user)
    profiles = [_profile_to_schema(profile) for profile in repo.list_profiles()]
    return ConnectorProfileListResponse(items=profiles, total=len(profiles))


@router.post("/profiles", status_code=status.HTTP_201_CREATED, response_model=ConnectorProfile, summary="Create a connector profile")
def create_connector_profile(
    request: Request,
    payload: ConnectorProfileCreateRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorProfile:
    require_csrf(request)
    _require_connector_admin(user)
    encrypted = encrypt_secret(dict(payload.secrets), _keyring())
    profile = repo.create_profile(
        name=payload.name,
        connector_type=payload.connector_type,
        public_config=dict(payload.public_config),
        encrypted_secrets=encrypted,
        created_by=user.id,
    )
    return _profile_to_schema(profile)


@router.put("/profiles/{profile_id}", response_model=ConnectorProfile, summary="Update a connector profile")
def update_connector_profile(
    profile_id: str,
    request: Request,
    payload: ConnectorProfileUpdateRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorProfile:
    require_csrf(request)
    _require_connector_admin(user)
    current = repo.get_profile(profile_id)
    if current is None:
        raise HTTPException(status_code=404, detail={"code": "connector_profile_not_found", "message": "Connector profile was not found."})
    encrypted = encrypt_secret(dict(payload.secrets), _keyring()) if payload.secrets is not None else None
    updated = repo.update_profile(
        profile_id,
        name=payload.name,
        public_config=dict(payload.public_config) if payload.public_config is not None else None,
        encrypted_secrets=encrypted,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "connector_profile_not_found", "message": "Connector profile was not found."})
    return _profile_to_schema(updated)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a connector profile")
def delete_connector_profile(
    profile_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> None:
    require_csrf(request)
    _require_connector_admin(user)
    if not repo.delete_profile(profile_id):
        raise HTTPException(status_code=404, detail={"code": "connector_profile_not_found", "message": "Connector profile was not found."})


@router.post("/profiles/{profile_id}/test", response_model=ConnectorTestResponse, summary="Test a connector profile")
def test_connector_profile(
    profile_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorTestResponse:
    require_csrf(request)
    _require_connector_admin(user)
    profile = _require_profile(repo, profile_id)
    connector = default_connector_registry().get(profile.connector_type)
    try:
        result = connector.test_connection(config=profile.public_config, secrets=_secrets(profile.encrypted_secrets))
        updated = repo.record_test_result(profile.id, status="ok", message=result.message)
        return ConnectorTestResponse(status="ok", message=result.message, detail=result.detail or {}, profile=_profile_to_schema(updated or profile))
    except Exception as exc:
        message = str(exc)[:500] or "Connector test failed."
        updated = repo.record_test_result(profile.id, status="failed", message=message)
        return ConnectorTestResponse(status="failed", message=message, detail={}, profile=_profile_to_schema(updated or profile))


@router.post("/profiles/{profile_id}/introspect", response_model=ConnectorSchemaSnapshot, summary="Capture connector schema introspection")
def introspect_connector_profile(
    profile_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorSchemaSnapshot:
    require_csrf(request)
    _require_connector_admin(user)
    profile = _require_profile(repo, profile_id)
    connector = default_connector_registry().get(profile.connector_type)
    try:
        schema = connector.introspect(config=profile.public_config, secrets=_secrets(profile.encrypted_secrets))
        snapshot = repo.save_introspection(profile_id=profile.id, connector_type=profile.connector_type, schema_json=schema, status="ok")
    except Exception as exc:
        snapshot = repo.save_introspection(
            profile_id=profile.id,
            connector_type=profile.connector_type,
            schema_json={},
            status="failed",
            error_message_safe=str(exc)[:500],
        )
    return _schema_to_response(snapshot)


@router.get(
    "/profiles/{profile_id}/schema-catalogs",
    response_model=ConnectorSchemaCatalogListResponse,
    summary="List approved database scope catalogs for a connector profile",
)
def list_connector_schema_catalogs(
    profile_id: str,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorSchemaCatalogListResponse:
    _require_connector_admin(user)
    _require_profile(repo, profile_id)
    catalogs = [_catalog_to_schema(catalog) for catalog in _current_schema_catalogs(repo.list_schema_catalogs(profile_id))]
    return ConnectorSchemaCatalogListResponse(items=catalogs, total=len(catalogs))


@router.post(
    "/profiles/{profile_id}/schema-catalogs",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectorSchemaCatalog,
    summary="Create a reviewable approved database scope catalog",
)
def create_connector_schema_catalog(
    profile_id: str,
    request: Request,
    payload: ConnectorSchemaCatalogCreateRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
) -> ConnectorSchemaCatalog:
    require_csrf(request)
    _require_connector_admin(user)
    profile = _require_profile(repo, profile_id)
    current = _current_schema_catalog(repo.list_schema_catalogs(profile_id))
    access_group_paths = _validated_catalog_access_group_paths(
        payload.group_path,
        payload.group_paths,
        current=current,
        user=user,
        identity_repo=identity_repo,
    )
    catalog_json = dict(payload.catalog_json or {})
    if not catalog_json:
        snapshot = repo.latest_introspection(profile_id)
        if snapshot is None or snapshot.status != "ok":
            raise HTTPException(
                status_code=409,
                detail={"code": "connector_schema_snapshot_required", "message": "Run connector introspection before creating a schema catalog."},
            )
        catalog_json = build_default_schema_catalog(snapshot.schema_json)
    catalog_json = schema_catalog_with_shared_group_paths(catalog_json, access_group_paths[1:])
    if current is not None:
        catalog = _update_schema_catalog_or_404(
            repo,
            current.id,
            status=payload.status,
            group_path=access_group_paths[0],
            clearance_level=payload.clearance_level,
            catalog_json=catalog_json,
            approved_by=user.id if payload.status == "approved" else None,
        )
    else:
        catalog = repo.save_schema_catalog(
            profile_id=profile.id,
            connector_type=profile.connector_type,
            catalog_json=catalog_json,
            status=payload.status,
            group_path=access_group_paths[0],
            clearance_level=payload.clearance_level,
            created_by=user.id,
            approved_by=user.id if payload.status == "approved" else None,
        )
    return _catalog_to_schema(catalog)


@router.post(
    "/profiles/{profile_id}/schema-catalogs/ai-draft",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectorSchemaCatalog,
    summary="Create an AI-enriched draft schema catalog for admin review",
)
def create_ai_schema_catalog_draft(
    profile_id: str,
    request: Request,
    payload: ConnectorSchemaCatalogAiDraftRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
) -> ConnectorSchemaCatalog:
    require_csrf(request)
    _require_connector_admin(user)
    profile = _require_profile(repo, profile_id)
    snapshot = repo.latest_introspection(profile_id)
    if snapshot is None or snapshot.status != "ok":
        raise HTTPException(
            status_code=409,
            detail={"code": "connector_schema_snapshot_required", "message": "Run connector introspection before creating an AI schema draft."},
        )
    catalog_json = initialize_schema_catalog_enrichment(build_default_schema_catalog(snapshot.schema_json))
    current = _current_schema_catalog(repo.list_schema_catalogs(profile_id))
    access_group_paths = _validated_catalog_access_group_paths(
        payload.group_path,
        payload.group_paths,
        current=current,
        user=user,
        identity_repo=identity_repo,
    )
    catalog_json = schema_catalog_with_shared_group_paths(catalog_json, access_group_paths[1:])
    if current is not None:
        catalog = _update_schema_catalog_or_404(
            repo,
            current.id,
            catalog_json=catalog_json,
            status="draft",
            group_path=access_group_paths[0],
            clearance_level=payload.clearance_level,
            approved_by=None,
        )
    else:
        catalog = repo.save_schema_catalog(
            profile_id=profile.id,
            connector_type=profile.connector_type,
            catalog_json=catalog_json,
            status="draft",
            group_path=access_group_paths[0],
            clearance_level=payload.clearance_level,
            created_by=user.id,
            approved_by=None,
        )
    return _catalog_to_schema(catalog)


@router.post(
    "/profiles/{profile_id}/schema-catalogs/{catalog_id}/ai-enrich-table",
    response_model=ConnectorSchemaCatalog,
    summary="Enrich one table in a draft schema catalog",
)
def enrich_connector_schema_catalog_table(
    profile_id: str,
    catalog_id: str,
    request: Request,
    payload: ConnectorSchemaCatalogTableEnrichRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
    runtime: SchemaEnrichmentRuntime = Depends(get_schema_enrichment_runtime),
) -> ConnectorSchemaCatalog:
    require_csrf(request)
    _require_connector_admin(user)
    profile = _require_profile(repo, profile_id)
    current = repo.get_schema_catalog(catalog_id)
    if current is None or current.profile_id != profile_id:
        raise HTTPException(status_code=404, detail={"code": "connector_schema_catalog_not_found", "message": "Connector schema catalog was not found."})
    if current.status not in {"draft", "reviewed"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "connector_schema_catalog_not_editable", "message": "Only draft or reviewed catalogs can be AI-enriched."},
        )
    if payload.table_key.strip().lower() not in schema_catalog_table_keys(current.catalog_json):
        raise HTTPException(
            status_code=404,
            detail={"code": "connector_schema_table_not_found", "message": "The requested table is not part of this schema catalog."},
        )
    try:
        catalog_json = enrich_schema_table_with_llm(
            current.catalog_json,
            table_key=payload.table_key,
            connector_type=profile.connector_type,
            profile_name=profile.name,
            llm=runtime.llm,
            model=runtime.model,
        )
    except SchemaEnrichmentError as exc:
        logger.info("Schema table enrichment failed for catalog %s table %s: %s", current.id, payload.table_key, exc)
        catalog_json = schema_catalog_with_table_enrichment_failure(
            current.catalog_json,
            table_key=payload.table_key,
            error_message=str(exc) or "Schema table enrichment failed.",
        )
    except Exception:
        logger.exception("Schema table enrichment failed for catalog %s table %s", current.id, payload.table_key)
        catalog_json = schema_catalog_with_table_enrichment_failure(
            current.catalog_json,
            table_key=payload.table_key,
            error_message="Schema table enrichment failed.",
        )
    updated = repo.update_schema_catalog(catalog_id, catalog_json=catalog_json)
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "connector_schema_catalog_not_found", "message": "Connector schema catalog was not found."})
    return _catalog_to_schema(updated)


@router.put(
    "/profiles/{profile_id}/schema-catalogs/{catalog_id}",
    response_model=ConnectorSchemaCatalog,
    summary="Update or approve a database scope catalog",
)
def update_connector_schema_catalog(
    profile_id: str,
    catalog_id: str,
    request: Request,
    payload: ConnectorSchemaCatalogUpdateRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
) -> ConnectorSchemaCatalog:
    require_csrf(request)
    _require_connector_admin(user)
    _require_profile(repo, profile_id)
    current = repo.get_schema_catalog(catalog_id)
    if current is None or current.profile_id != profile_id:
        raise HTTPException(status_code=404, detail={"code": "connector_schema_catalog_not_found", "message": "Connector schema catalog was not found."})
    catalog_json = dict(payload.catalog_json) if payload.catalog_json is not None else dict(current.catalog_json)
    update_kwargs: dict[str, Any] = {
        "status": payload.status,
        "clearance_level": payload.clearance_level,
    }
    if payload.group_path is not None or payload.group_paths is not None:
        access_group_paths = _validated_catalog_access_group_paths(
            payload.group_path,
            payload.group_paths,
            current=current,
            user=user,
            identity_repo=identity_repo,
        )
        update_kwargs["group_path"] = access_group_paths[0]
        catalog_json = schema_catalog_with_shared_group_paths(catalog_json, access_group_paths[1:])
    if payload.catalog_json is not None or payload.group_path is not None or payload.group_paths is not None:
        update_kwargs["catalog_json"] = catalog_json
    if payload.status is not None:
        update_kwargs["approved_by"] = user.id if payload.status == "approved" else None
    updated = _update_schema_catalog_or_404(repo, catalog_id, **update_kwargs)
    return _catalog_to_schema(updated)


def _require_connector_admin(user: UserRecord) -> None:
    if not can_manage_spaces(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "connector_admin_required", "message": "Connector profile management requires a platform or space admin."},
        )


def _require_profile(repo: ConnectorProfileRepository, profile_id: str):
    profile = repo.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail={"code": "connector_profile_not_found", "message": "Connector profile was not found."})
    return profile


def _current_schema_catalog(catalogs: list[Any]) -> Any | None:
    current = _current_schema_catalogs(catalogs)
    return current[0] if current else None


def _current_schema_catalogs(catalogs: list[Any]) -> list[Any]:
    by_profile: dict[str, Any] = {}
    for catalog in catalogs:
        if catalog.profile_id not in by_profile:
            by_profile[catalog.profile_id] = catalog
    return list(by_profile.values())


def _validated_catalog_access_group_paths(
    owner_group_path: str | None,
    group_paths: list[str] | None,
    *,
    current: Any | None,
    user: UserRecord,
    identity_repo: IdentityRepository,
) -> list[str]:
    from ...auth.abac import normalize_group_path

    try:
        owner = normalize_group_path(owner_group_path or (current.group_path if current is not None else ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_group_path", "message": str(exc)}) from exc
    requested = group_paths if group_paths is not None else []
    candidates = [owner, *requested] if requested else [owner]
    normalized: list[str] = []
    seen: set[str] = set()
    known = {group.path for group in identity_repo.list_groups()}
    for raw_path in candidates:
        try:
            group_path = normalize_group_path(raw_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_group_path", "message": str(exc)}) from exc
        if group_path not in known:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "group_not_found", "message": f"Knowledge Space does not exist: {group_path}"},
            )
        if not can_manage_group_path(user, group_path):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "group_scope_forbidden", "message": "Knowledge Space is outside the connector manager's scope."},
            )
        if group_path not in seen:
            seen.add(group_path)
            normalized.append(group_path)
    return normalized


def _update_schema_catalog_or_404(repo: ConnectorProfileRepository, catalog_id: str, **kwargs: Any):
    updated = repo.update_schema_catalog(catalog_id, **kwargs)
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "connector_schema_catalog_not_found", "message": "Connector schema catalog was not found."})
    return updated


def _profile_to_schema(profile) -> ConnectorProfile:
    redacted = redact_secrets(_secrets(profile.encrypted_secrets))
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


def _schema_to_response(snapshot) -> ConnectorSchemaSnapshot:
    return ConnectorSchemaSnapshot(
        id=snapshot.id,
        profile_id=snapshot.profile_id,
        connector_type=snapshot.connector_type,
        schema_json=dict(snapshot.schema_json),
        status=snapshot.status,
        error_message=snapshot.error_message_safe,
        created_at=snapshot.created_at,
    )


def _catalog_to_schema(catalog) -> ConnectorSchemaCatalog:
    shared_group_paths = schema_catalog_shared_group_paths(catalog.catalog_json)
    access_group_paths = schema_catalog_access_group_paths(catalog.group_path, catalog.catalog_json)
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


def _secrets(encrypted: str) -> dict[str, object]:
    return decrypt_secret(encrypted, _keyring())


def _keyring():
    return keyring_from_settings(settings.connector_secrets_key, settings.connector_secrets_key_ring)
