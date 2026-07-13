"""Shared HTTP authorization and scope preparation for query routes."""

from fastapi import HTTPException, status

from ..auth.abac import normalize_group_path
from ..auth.context import UserContext
from ..auth.identity_models import IdentityRepository, UserRecord
from ..auth.permissions import can_query, has_exact_group_scope, is_global_admin
from ..connectors.repositories import ConnectorProfileRepository
from ..ingestion.folders.models import FolderScheduleRepository
from .schemas import QueryRequest
from .source_resolution import QuerySourceAccessError, validate_query_source_access


def query_request_for_user(
    payload: QueryRequest,
    user: UserRecord,
    repo: IdentityRepository,
) -> QueryRequest:
    require_query_user(user)
    group_path = validated_query_group_path(payload.group_path, user, repo)
    if group_path == payload.group_path:
        return payload
    return payload.model_copy(update={"group_path": group_path})


def validated_query_group_path(
    group_path: str | None,
    user: UserRecord,
    repo: IdentityRepository,
) -> str | None:
    if group_path is None:
        return None
    try:
        normalized = normalize_group_path(group_path)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_query_group",
                "message": "Query Knowledge Space is invalid.",
            },
        ) from exc
    if is_global_admin(user):
        known_groups = {group.path for group in repo.list_groups()}
        if normalized in known_groups:
            return normalized
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "query_group_not_found",
                "message": "Query Knowledge Space does not exist.",
            },
        )
    if not has_exact_group_scope(user, normalized):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "query_group_forbidden",
                "message": "User cannot query this Knowledge Space.",
            },
        )
    return normalized


def validate_query_source_for_user(
    payload: QueryRequest,
    user_context: UserContext,
    schedule_repo: FolderScheduleRepository,
    connector_profile_repo: ConnectorProfileRepository,
) -> None:
    if payload.group_path:
        user_context = UserContext(
            user_id=user_context.user_id,
            email=user_context.email,
            account_type=user_context.account_type,
            group_paths=(payload.group_path,),
            clearance_level=user_context.clearance_level,
            permission_version=user_context.permission_version,
        )
    try:
        validate_query_source_access(
            source_id=payload.query_source_id,
            user=user_context,
            schedule_repo=schedule_repo,
            connector_profile_repo=connector_profile_repo,
        )
    except QuerySourceAccessError as exc:
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if exc.code == "invalid_query_source"
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


def user_context(user: UserRecord, repo: IdentityRepository) -> UserContext:
    group_paths = (
        tuple(group.path for group in repo.list_groups())
        if is_global_admin(user)
        else user.group_paths
    )
    return UserContext(
        user_id=user.id,
        email=user.email,
        account_type=user.account_type,
        group_paths=group_paths,
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
    )


def require_query_user(user: UserRecord) -> None:
    if not can_query(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "query_role_forbidden",
                "message": "User account type cannot query Knowledge Spaces.",
            },
        )
