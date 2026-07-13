"""Connector profile lifecycle and introspection routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.dependencies import require_csrf, require_current_user
from ..auth.identity_models import UserRecord
from ..schemas.connectors import (
    ConnectorProfile,
    ConnectorProfileCreateRequest,
    ConnectorProfileListResponse,
    ConnectorProfileUpdateRequest,
    ConnectorSchemaSnapshot,
    ConnectorTestResponse,
)
from .crypto import encrypt_secret
from .http_presenters import profile_to_schema, schema_to_response
from .registry import default_connector_registry
from .repositories import ConnectorProfileRepository, get_connector_profile_repository
from .route_support import keyring, require_connector_admin, require_profile, secrets

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get(
    "/profiles",
    response_model=ConnectorProfileListResponse,
    summary="List connector profiles",
)
def list_connector_profiles(
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorProfileListResponse:
    require_connector_admin(user)
    profiles = [profile_to_schema(profile) for profile in repo.list_profiles()]
    return ConnectorProfileListResponse(items=profiles, total=len(profiles))


@router.post(
    "/profiles",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectorProfile,
    summary="Create a connector profile",
)
def create_connector_profile(
    request: Request,
    payload: ConnectorProfileCreateRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorProfile:
    require_csrf(request)
    require_connector_admin(user)
    encrypted = encrypt_secret(dict(payload.secrets), keyring())
    profile = repo.create_profile(
        name=payload.name,
        connector_type=payload.connector_type,
        public_config=dict(payload.public_config),
        encrypted_secrets=encrypted,
        created_by=user.id,
    )
    return profile_to_schema(profile)


@router.put(
    "/profiles/{profile_id}",
    response_model=ConnectorProfile,
    summary="Update a connector profile",
)
def update_connector_profile(
    profile_id: str,
    request: Request,
    payload: ConnectorProfileUpdateRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorProfile:
    require_csrf(request)
    require_connector_admin(user)
    current = repo.get_profile(profile_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_profile_not_found",
                "message": "Connector profile was not found.",
            },
        )
    encrypted = (
        encrypt_secret(dict(payload.secrets), keyring())
        if payload.secrets is not None
        else None
    )
    updated = repo.update_profile(
        profile_id,
        name=payload.name,
        public_config=(
            dict(payload.public_config) if payload.public_config is not None else None
        ),
        encrypted_secrets=encrypted,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_profile_not_found",
                "message": "Connector profile was not found.",
            },
        )
    return profile_to_schema(updated)


@router.delete(
    "/profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connector profile",
)
def delete_connector_profile(
    profile_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> None:
    require_csrf(request)
    require_connector_admin(user)
    if not repo.delete_profile(profile_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_profile_not_found",
                "message": "Connector profile was not found.",
            },
        )


@router.post(
    "/profiles/{profile_id}/test",
    response_model=ConnectorTestResponse,
    summary="Test a connector profile",
)
def test_connector_profile(
    profile_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorTestResponse:
    require_csrf(request)
    require_connector_admin(user)
    profile = require_profile(repo, profile_id)
    connector = default_connector_registry().get(profile.connector_type)
    try:
        result = connector.test_connection(
            config=profile.public_config,
            secrets=secrets(profile.encrypted_secrets),
        )
        updated = repo.record_test_result(
            profile.id,
            status="ok",
            message=result.message,
        )
        return ConnectorTestResponse(
            status="ok",
            message=result.message,
            detail=result.detail or {},
            profile=profile_to_schema(updated or profile),
        )
    except Exception as exc:
        message = str(exc)[:500] or "Connector test failed."
        updated = repo.record_test_result(
            profile.id,
            status="failed",
            message=message,
        )
        return ConnectorTestResponse(
            status="failed",
            message=message,
            detail={},
            profile=profile_to_schema(updated or profile),
        )


@router.post(
    "/profiles/{profile_id}/introspect",
    response_model=ConnectorSchemaSnapshot,
    summary="Capture connector schema introspection",
)
def introspect_connector_profile(
    profile_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> ConnectorSchemaSnapshot:
    require_csrf(request)
    require_connector_admin(user)
    profile = require_profile(repo, profile_id)
    connector = default_connector_registry().get(profile.connector_type)
    try:
        schema = connector.introspect(
            config=profile.public_config,
            secrets=secrets(profile.encrypted_secrets),
        )
        snapshot = repo.save_introspection(
            profile_id=profile.id,
            connector_type=profile.connector_type,
            schema_json=schema,
            status="ok",
        )
    except Exception as exc:
        snapshot = repo.save_introspection(
            profile_id=profile.id,
            connector_type=profile.connector_type,
            schema_json={},
            status="failed",
            error_message_safe=str(exc)[:500],
        )
    return schema_to_response(snapshot)
