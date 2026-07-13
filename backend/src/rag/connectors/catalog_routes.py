"""Connector schema catalog lifecycle routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.dependencies import require_csrf, require_current_user
from ..auth.identity_models import IdentityRepository, UserRecord
from ..auth.identity_repository import get_identity_repository
from ..schemas.connectors import (
    ConnectorSchemaCatalog,
    ConnectorSchemaCatalogCreateRequest,
    ConnectorSchemaCatalogListResponse,
    ConnectorSchemaCatalogUpdateRequest,
)
from .http_presenters import catalog_to_schema
from .repositories import ConnectorProfileRepository, get_connector_profile_repository
from .route_support import (
    current_schema_catalog,
    current_schema_catalogs,
    require_connector_admin,
    require_profile,
    update_schema_catalog_or_404,
    validated_catalog_access_group_paths,
)
from .schema_catalog import (
    build_default_schema_catalog,
    schema_catalog_with_shared_group_paths,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


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
    require_connector_admin(user)
    require_profile(repo, profile_id)
    catalogs = [
        catalog_to_schema(catalog)
        for catalog in current_schema_catalogs(repo.list_schema_catalogs(profile_id))
    ]
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
    require_connector_admin(user)
    profile = require_profile(repo, profile_id)
    current = current_schema_catalog(repo.list_schema_catalogs(profile_id))
    access_group_paths = validated_catalog_access_group_paths(
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
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "connector_schema_snapshot_required",
                    "message": "Run connector introspection before creating a schema catalog.",
                },
            )
        catalog_json = build_default_schema_catalog(snapshot.schema_json)
    catalog_json = schema_catalog_with_shared_group_paths(
        catalog_json,
        access_group_paths[1:],
    )
    if current is not None:
        catalog = update_schema_catalog_or_404(
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
    return catalog_to_schema(catalog)


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
    require_connector_admin(user)
    require_profile(repo, profile_id)
    current = repo.get_schema_catalog(catalog_id)
    if current is None or current.profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_schema_catalog_not_found",
                "message": "Connector schema catalog was not found.",
            },
        )
    catalog_json = (
        dict(payload.catalog_json)
        if payload.catalog_json is not None
        else dict(current.catalog_json)
    )
    update_kwargs: dict[str, Any] = {
        "status": payload.status,
        "clearance_level": payload.clearance_level,
    }
    if payload.group_path is not None or payload.group_paths is not None:
        access_group_paths = validated_catalog_access_group_paths(
            payload.group_path,
            payload.group_paths,
            current=current,
            user=user,
            identity_repo=identity_repo,
        )
        update_kwargs["group_path"] = access_group_paths[0]
        catalog_json = schema_catalog_with_shared_group_paths(
            catalog_json,
            access_group_paths[1:],
        )
    if (
        payload.catalog_json is not None
        or payload.group_path is not None
        or payload.group_paths is not None
    ):
        update_kwargs["catalog_json"] = catalog_json
    if payload.status is not None:
        update_kwargs["approved_by"] = user.id if payload.status == "approved" else None
    updated = update_schema_catalog_or_404(repo, catalog_id, **update_kwargs)
    return catalog_to_schema(updated)
