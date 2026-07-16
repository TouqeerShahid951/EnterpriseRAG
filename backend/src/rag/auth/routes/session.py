from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from rag.auth.dependencies import clear_auth_cookies, current_user_from_token, require_csrf, require_current_user, set_auth_cookies, to_auth_user
from rag.auth.issued_tokens import REFRESH_TOKEN_TYPE, create_auth_tokens
from rag.auth.passwords import hash_password, verify_password
from rag.auth.refresh_sessions import RefreshSessionStore, auth_idle_ttl_seconds, get_refresh_session_store
from rag.core.config import settings
from rag.documents.repository import DocumentRepository, get_document_repository
from rag.auth.identity_models import IdentityRepository, UserRecord
from rag.auth.identity_repository import get_identity_repository
from rag.auth.schemas.session import (
    AuthUser,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RefreshResponse,
)
from rag.shared.contracts.http import ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    responses={
        status.HTTP_200_OK: {"model": LoginResponse},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    },
    summary="Authenticate and set httpOnly auth cookies",
)
def login(
    payload: LoginRequest,
    response: Response,
    repo: IdentityRepository = Depends(get_identity_repository),
    sessions: RefreshSessionStore = Depends(get_refresh_session_store),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> LoginResponse:
    user = repo.get_user_by_email(payload.email)
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Invalid email or password."},
        )

    repo.set_last_login(user.id)
    user = repo.get_user_by_id(user.id) or user
    csrf_token = issue_login(response, user, sessions)
    audit_auth(audit_repo, event_type="auth.login", user=user)
    return LoginResponse(user=to_auth_user(user), csrf_token=csrf_token)


@router.post(
    "/logout",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_202_ACCEPTED: {"model": LogoutResponse},
    },
    summary="Clear auth cookies and invalidate refresh state",
)
def logout(
    request: Request,
    response: Response,
    sessions: RefreshSessionStore = Depends(get_refresh_session_store),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> LogoutResponse:
    require_csrf(request)
    token = request.cookies.get(settings.refresh_cookie_name)
    if token:
        sessions.revoke(token)
    audit_auth(audit_repo, event_type="auth.logout", user=None)
    clear_auth_cookies(response)
    return LogoutResponse()


@router.post(
    "/refresh",
    responses={
        status.HTTP_200_OK: {"model": RefreshResponse},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    },
    summary="Rotate refresh token and issue a new access cookie",
)
def refresh(
    request: Request,
    response: Response,
    repo: IdentityRepository = Depends(get_identity_repository),
    sessions: RefreshSessionStore = Depends(get_refresh_session_store),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> RefreshResponse:
    require_csrf(request)
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "refresh_required", "message": "Refresh token required."},
        )
    user = current_user_from_token(token, token_type=REFRESH_TOKEN_TYPE, repo=repo)
    csrf_token = issue_refresh(response, user, token, sessions)
    audit_auth(audit_repo, event_type="auth.refresh", user=user)
    return RefreshResponse(user=to_auth_user(user), csrf_token=csrf_token)


@router.get(
    "/me",
    responses={
        status.HTTP_200_OK: {"model": AuthUser},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    },
    summary="Read the authenticated user context",
)
def read_current_user(user: UserRecord = Depends(require_current_user)) -> AuthUser:
    return to_auth_user(user)


@router.post(
    "/change-password",
    response_model=AuthUser,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
    summary="Change password for admin-created accounts",
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: IdentityRepository = Depends(get_identity_repository),
) -> AuthUser:
    require_csrf(request)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_current_password", "message": "Current password is incorrect."},
        )
    updated = repo.set_user_password(user.id, hash_password(payload.new_password))
    return to_auth_user(updated or user)


def issue_login(response: Response, user: UserRecord, sessions: RefreshSessionStore) -> str:
    access_token, refresh_token, csrf_token = create_auth_tokens(user)
    sessions.remember(user_id=user.id, refresh_token=refresh_token, ttl_seconds=auth_idle_ttl_seconds())
    set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token, csrf_token=csrf_token)
    return csrf_token


def issue_refresh(
    response: Response,
    user: UserRecord,
    old_refresh_token: str,
    sessions: RefreshSessionStore,
) -> str:
    access_token, refresh_token, csrf_token = create_auth_tokens(user)
    rotated = sessions.rotate(
        user_id=user.id,
        old_token=old_refresh_token,
        new_token=refresh_token,
        ttl_seconds=auth_idle_ttl_seconds(),
    )
    if not rotated:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_refresh_session", "message": "Refresh session is invalid or expired."},
        )
    set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token, csrf_token=csrf_token)
    return csrf_token


def audit_auth(repo: DocumentRepository, *, event_type: str, user: UserRecord | None) -> None:
    repo.append_audit_event(
        event_type=event_type,
        actor_id=user.id if user else None,
        target_type="user" if user else None,
        target_id=user.id if user else None,
        payload={"email": user.email} if user and event_type == "auth.login" else {},
    )
