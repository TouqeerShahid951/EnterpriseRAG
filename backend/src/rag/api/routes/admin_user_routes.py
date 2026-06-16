"""Admin user-management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_csrf, require_user_manager
from ...auth.permissions import AccountType
from ...shared.contracts.clearance import MAX_CLEARANCE_LEVEL, normalize_clearance_level
from ...auth.passwords import hash_password
from ...repositories.documents import DocumentRepository, get_document_repository
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...schemas.admin import UserAdmin, UserCreateRequest, UserGroupRequest, UserListResponse, UserUpdateRequest
from ...schemas.common import ErrorResponse
from .admin_common import (
    require_admin_if_users_exist,
    require_can_assign_user,
    require_can_manage_target_user,
    user_to_admin,
    visible_users_for_manager,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=UserListResponse, summary="List users")
def list_users(
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserListResponse:
    users = [user_to_admin(record) for record in visible_users_for_manager(user, repo.list_users())]
    return UserListResponse(items=users, total=len(users))


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {"model": UserAdmin},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
    summary="Create an admin-managed user with an initial password",
)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserAdmin:
    group_paths = list(payload.group_paths)
    account_type: AccountType = payload.account_type or "member"
    clearance_level = normalize_clearance_level(payload.clearance_level)
    if repo.count_users() == 0:
        account_type = "platform_admin"
        clearance_level = MAX_CLEARANCE_LEVEL
    else:
        require_csrf(request)
        actor = require_admin_if_users_exist(request, repo)
        if actor is not None:
            require_can_assign_user(actor, account_type, group_paths, clearance_level)
    try:
        user = repo.create_user(
            email=payload.email,
            name=payload.name,
            password_hash=hash_password(payload.initial_password),
            group_paths=group_paths,
            is_active=payload.is_active,
            account_type=account_type,
            clearance_level=clearance_level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_user", "message": str(exc)}) from exc
    return user_to_admin(user)


@router.put(
    "/users/{user_id}",
    responses={
        status.HTTP_200_OK: {"model": UserAdmin},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Update a user",
)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserAdmin:
    current = repo.get_user_by_id(user_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    require_can_manage_target_user(user, current)
    next_group_paths = current.group_paths if payload.group_paths is None else tuple(payload.group_paths)
    next_account_type = current.account_type if payload.account_type is None else payload.account_type
    next_clearance = current.clearance_level if payload.clearance_level is None else normalize_clearance_level(payload.clearance_level)
    require_can_assign_user(user, next_account_type, list(next_group_paths), next_clearance)
    try:
        updated = repo.update_user(
            user_id,
            name=payload.name,
            group_paths=payload.group_paths,
            is_active=payload.is_active,
            account_type=payload.account_type,
            clearance_level=payload.clearance_level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_user", "message": str(exc)}) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    return user_to_admin(updated)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Permanently delete a user",
)
def delete_user(
    user_id: str,
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> None:
    target = repo.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    if target.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "cannot_delete_current_user", "message": "You cannot delete the account for your current session."},
        )
    require_can_manage_target_user(user, target)
    if not repo.delete_user(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    audit_repo.append_audit_event(
        event_type="admin.user.deleted",
        actor_id=user.id,
        target_type="user",
        target_id=target.id,
        payload={"email": target.email, "name": target.name, "account_type": target.account_type},
    )


@router.get(
    "/users/{user_id}/groups",
    response_model=list[str],
    summary="List a user's direct group memberships",
)
def list_user_groups(
    user_id: str,
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> list[str]:
    target = repo.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    require_can_manage_target_user(user, target)
    return list(target.group_paths)


@router.post(
    "/users/{user_id}/groups",
    response_model=UserAdmin,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Add a direct user group membership",
)
def add_user_group(
    user_id: str,
    payload: UserGroupRequest,
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserAdmin:
    target = repo.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    require_can_manage_target_user(user, target)
    require_can_assign_user(user, target.account_type, sorted({*target.group_paths, normalize_group_path(payload.group_path)}), target.clearance_level)
    try:
        updated = repo.add_user_group(user_id, payload.group_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_group", "message": str(exc)}) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    return user_to_admin(updated)


@router.delete(
    "/users/{user_id}/groups",
    response_model=UserAdmin,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
    summary="Remove a direct user group membership",
)
def remove_user_group(
    user_id: str,
    payload: UserGroupRequest,
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserAdmin:
    target = repo.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    require_can_manage_target_user(user, target)
    normalized_group = normalize_group_path(payload.group_path)
    next_groups = [path for path in target.group_paths if path != normalized_group]
    require_can_assign_user(user, target.account_type, next_groups, target.clearance_level)
    updated = repo.remove_user_group(user_id, payload.group_path)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    return user_to_admin(updated)
