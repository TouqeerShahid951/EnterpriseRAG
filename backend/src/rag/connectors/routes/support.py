"""Shared authorization and persistence mechanics for connector HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from rag.auth.abac import normalize_group_path
from rag.auth.identity_models import IdentityRepository, UserRecord
from rag.auth.permissions import can_manage_group_path, can_manage_spaces
from rag.core.config import settings
from rag.connectors.crypto import decrypt_secret, keyring_from_settings
from rag.connectors.models import ConnectorProfileRecord, ConnectorSchemaCatalogRecord
from rag.connectors.repositories import ConnectorProfileRepository


def require_connector_admin(user: UserRecord) -> None:
    if not can_manage_spaces(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "connector_admin_required",
                "message": "Connector profile management requires a platform or space admin.",
            },
        )


def require_profile(
    repo: ConnectorProfileRepository,
    profile_id: str,
) -> ConnectorProfileRecord:
    profile = repo.get_profile(profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_profile_not_found",
                "message": "Connector profile was not found.",
            },
        )
    return profile


def current_schema_catalog(
    catalogs: list[ConnectorSchemaCatalogRecord],
) -> ConnectorSchemaCatalogRecord | None:
    current = current_schema_catalogs(catalogs)
    return current[0] if current else None


def current_schema_catalogs(
    catalogs: list[ConnectorSchemaCatalogRecord],
) -> list[ConnectorSchemaCatalogRecord]:
    by_profile: dict[str, ConnectorSchemaCatalogRecord] = {}
    for catalog in catalogs:
        if catalog.profile_id not in by_profile:
            by_profile[catalog.profile_id] = catalog
    return list(by_profile.values())


def validated_catalog_access_group_paths(
    owner_group_path: str | None,
    group_paths: list[str] | None,
    *,
    current: ConnectorSchemaCatalogRecord | None,
    user: UserRecord,
    identity_repo: IdentityRepository,
) -> list[str]:
    try:
        owner = normalize_group_path(
            owner_group_path or (current.group_path if current is not None else "")
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_group_path", "message": str(exc)},
        ) from exc
    requested = group_paths if group_paths is not None else []
    candidates = [owner, *requested] if requested else [owner]
    normalized: list[str] = []
    seen: set[str] = set()
    known = {group.path for group in identity_repo.list_groups()}
    for raw_path in candidates:
        try:
            group_path = normalize_group_path(raw_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_group_path", "message": str(exc)},
            ) from exc
        if group_path not in known:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "group_not_found",
                    "message": f"Knowledge Space does not exist: {group_path}",
                },
            )
        if not can_manage_group_path(user, group_path):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "group_scope_forbidden",
                    "message": "Knowledge Space is outside the connector manager's scope.",
                },
            )
        if group_path not in seen:
            seen.add(group_path)
            normalized.append(group_path)
    return normalized


def update_schema_catalog_or_404(
    repo: ConnectorProfileRepository,
    catalog_id: str,
    **kwargs: Any,
) -> ConnectorSchemaCatalogRecord:
    updated = repo.update_schema_catalog(catalog_id, **kwargs)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_schema_catalog_not_found",
                "message": "Connector schema catalog was not found.",
            },
        )
    return updated


def secrets(encrypted: str) -> dict[str, object]:
    return decrypt_secret(encrypted, keyring())


def keyring():
    return keyring_from_settings(
        settings.connector_secrets_key,
        settings.connector_secrets_key_ring,
    )
