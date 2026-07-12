"""Admin user-management routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_csrf, require_user_manager
from ...auth.permissions import AccountType, is_global_admin
from ...auth.refresh_sessions import RefreshSessionStore, get_refresh_session_store
from ...shared.contracts.clearance import MAX_CLEARANCE_LEVEL, normalize_clearance_level
from ...auth.passwords import hash_password
from ...query.chat_history_models import ChatSessionRecord
from ...query.chat_history_repository import ChatHistoryRepository, get_chat_history_repository
from ...documents.repository import DocumentRepository, get_document_repository
from ...auth.identity_models import IdentityRepository, UserRecord
from ...auth.identity_repository import get_identity_repository
from ...schemas.admin import UserAdmin, UserCreateRequest, UserGroupRequest, UserListResponse, UserPasswordResetRequest, UserUpdateRequest
from ...schemas.common import ErrorResponse
from ...schemas.query import ChatSession, ChatSessionListResponse, ChatSessionSummary
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


@router.get(
    "/users/{user_id}/chat-activity",
    response_model=ChatSessionListResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="List saved chat sessions for an admin-managed user",
)
def list_user_chat_activity(
    user_id: str,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
    chat_repo: ChatHistoryRepository = Depends(get_chat_history_repository),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> ChatSessionListResponse:
    target = _target_user_or_404(user_id, repo)
    _require_can_view_chat_activity(user, target)
    sessions = chat_repo.list_sessions(user_id=target.id, permission_version=target.permission_version, limit=limit, offset=offset)
    total = chat_repo.count_sessions(user_id=target.id, permission_version=target.permission_version)
    audit_repo.append_audit_event(
        event_type="admin.user.chat_activity_viewed",
        actor_id=user.id,
        target_type="user",
        target_id=target.id,
        payload={
            "email": target.email,
            "permission_version": target.permission_version,
            "result_count": len(sessions),
            "total": total,
        },
    )
    return ChatSessionListResponse(
        items=[_chat_session_summary_response(session) for session in sessions],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/users/{user_id}/chat-activity/{session_id}",
    response_model=ChatSession,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Read a saved chat session for an admin-managed user",
)
def get_user_chat_activity_session(
    user_id: str,
    session_id: str,
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
    chat_repo: ChatHistoryRepository = Depends(get_chat_history_repository),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> ChatSession:
    target = _target_user_or_404(user_id, repo)
    _require_can_view_chat_activity(user, target)
    session = chat_repo.get_session(session_id=session_id, user_id=target.id, permission_version=target.permission_version)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "chat_session_not_found", "message": "Chat session was not found."},
        )
    audit_repo.append_audit_event(
        event_type="admin.user.chat_session_viewed",
        actor_id=user.id,
        target_type="user",
        target_id=target.id,
        payload={
            "email": target.email,
            "permission_version": target.permission_version,
            "session_id": session.id,
            "question_count": session.question_count if session.question_count is not None else _question_count(session.turns),
        },
    )
    return _chat_session_response(session)


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
    sessions: RefreshSessionStore = Depends(get_refresh_session_store),
) -> UserAdmin:
    group_paths = list(payload.group_paths)
    account_type: AccountType = payload.account_type or "member"
    clearance_level = normalize_clearance_level(payload.clearance_level)
    if repo.count_users() == 0:
        account_type = "platform_admin"
        clearance_level = MAX_CLEARANCE_LEVEL
    else:
        require_csrf(request)
        actor = require_admin_if_users_exist(request, repo, sessions)
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


@router.post(
    "/users/{user_id}/reset-password",
    response_model=UserAdmin,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Reset a managed user's password",
)
def reset_user_password(
    user_id: str,
    payload: UserPasswordResetRequest,
    user: UserRecord = Depends(require_user_manager),
    repo: IdentityRepository = Depends(get_identity_repository),
    sessions: RefreshSessionStore = Depends(get_refresh_session_store),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> UserAdmin:
    target = _target_user_or_404(user_id, repo)
    if target.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "cannot_reset_current_user", "message": "Use Account Management to change the password for your current session."},
        )
    require_can_manage_target_user(user, target)
    try:
        password_hash = hash_password(payload.temporary_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_password", "message": str(exc)}) from exc
    sessions.revoke_user(target.id)
    updated = repo.set_user_password(user_id, password_hash, must_change_password=True)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    audit_repo.append_audit_event(
        event_type="admin.user.password_reset",
        actor_id=user.id,
        target_type="user",
        target_id=target.id,
        payload={"email": target.email, "name": target.name, "account_type": target.account_type, "must_change_password": True},
    )
    return user_to_admin(updated)


def _target_user_or_404(user_id: str, repo: IdentityRepository) -> UserRecord:
    target = repo.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "user_not_found", "message": "User was not found."})
    return target


def _require_can_view_chat_activity(actor: UserRecord, target: UserRecord) -> None:
    if not is_global_admin(actor):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "global_admin_required", "message": "Global administrator account type required to view user chat activity."},
        )
    require_can_manage_target_user(actor, target)


def _chat_session_response(session: ChatSessionRecord) -> ChatSession:
    return ChatSession(
        id=session.id,
        title=session.title,
        created_at=_isoformat(session.created_at),
        updated_at=_isoformat(session.updated_at),
        turns=list(session.turns),
    )


def _chat_session_summary_response(session: ChatSessionRecord) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        created_at=_isoformat(session.created_at),
        updated_at=_isoformat(session.updated_at),
        question_count=session.question_count if session.question_count is not None else _question_count(session.turns),
    )


def _isoformat(value: datetime | None) -> str:
    return (value or datetime.now(UTC)).isoformat()


def _question_count(turns: tuple[dict[str, object], ...]) -> int:
    return sum(1 for turn in turns if turn.get("role") == "user")


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
