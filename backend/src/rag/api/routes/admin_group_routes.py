"""Admin group-management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ...auth.dependencies import require_admin_user, require_csrf, require_current_user
from ...auth.permissions import can_manage_spaces, can_manage_users
from ...auth.refresh_sessions import RefreshSessionStore, get_refresh_session_store
from ...auth.identity_models import IdentityRepository, UserRecord
from ...auth.identity_repository import get_identity_repository
from ...schemas.admin import Group, GroupCreateRequest, GroupDeleteRequest, GroupListResponse, GroupUpdateRequest
from ...schemas.common import ErrorResponse, StubResponse
from .route_responses import not_implemented
from .admin_common import group_to_schema, require_can_manage_group, visible_groups_for_user

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/groups", response_model=GroupListResponse, summary="List the group tree")
def list_groups(
    request: Request,
    repo: IdentityRepository = Depends(get_identity_repository),
    sessions: RefreshSessionStore = Depends(get_refresh_session_store),
) -> GroupListResponse:
    if repo.count_users() == 0:
        return GroupListResponse(items=[group_to_schema(group) for group in repo.list_groups()])
    user = require_current_user(request, repo, sessions)
    if not (can_manage_users(user) or can_manage_spaces(user) or user.account_type == "auditor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "space_metadata_forbidden", "message": "User cannot list Knowledge Space metadata."},
        )
    return GroupListResponse(items=[group_to_schema(group) for group in visible_groups_for_user(user, repo.list_groups())])


@router.post(
    "/groups",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {"model": Group},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
    summary="Create a group",
)
def create_group(
    payload: GroupCreateRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> Group:
    require_csrf(request)
    if not can_manage_spaces(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "space_manager_required", "message": "Knowledge Space management account type required."},
        )
    require_can_manage_group(user, payload.path)
    try:
        return group_to_schema(repo.create_group(path=payload.path, name=payload.name))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_group", "message": str(exc)}) from exc


@router.put(
    "/groups",
    responses={
        status.HTTP_200_OK: {"model": Group},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Rename or move a group",
)
def update_group(
    payload: GroupUpdateRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> Group:
    require_csrf(request)
    if not can_manage_spaces(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "space_manager_required", "message": "Knowledge Space management account type required."},
        )
    require_can_manage_group(user, payload.path)
    try:
        group = repo.update_group(path=payload.path, name=payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_group", "message": str(exc)}) from exc
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "group_not_found", "message": "Group was not found."})
    return group_to_schema(group)


@router.delete(
    "/groups",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Delete an empty group",
)
def delete_group(
    payload: GroupDeleteRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> Response:
    require_csrf(request)
    if not can_manage_spaces(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "space_manager_required", "message": "Knowledge Space management account type required."},
        )
    require_can_manage_group(user, payload.path)
    try:
        deleted = repo.delete_group(payload.path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "group_not_empty", "message": str(exc)}) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "group_not_found", "message": "Group was not found."})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/groups/import",
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"model": StubResponse}},
    summary="Import a group tree after preview",
)
def import_groups(payload: dict, user: UserRecord = Depends(require_admin_user)):
    _ = user
    _ = payload
    return not_implemented("Group import is reserved for Milestone 2.")
