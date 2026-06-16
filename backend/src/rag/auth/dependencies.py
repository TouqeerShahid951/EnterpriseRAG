"""Authentication dependencies shared by public route handlers."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response, status

from ..core.config import settings
from ..repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ..schemas.auth import AuthUser
from .issued_tokens import ACCESS_TOKEN_TYPE
from .permissions import can_manage_users, can_manage_workspace_config, can_review, is_global_admin
from .tokens import TokenError, decode_token


def to_auth_user(user: UserRecord) -> AuthUser:
    return AuthUser(
        user_id=user.id,
        email=user.email,
        account_type=user.account_type,
        group_paths=list(user.group_paths),
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
        must_change_password=user.must_change_password,
    )


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str, csrf_token: str) -> None:
    cookie_args = {
        "secure": settings.auth_cookie_secure,
        "samesite": settings.auth_cookie_samesite,
        "path": "/",
    }
    response.set_cookie(
        settings.access_cookie_name,
        access_token,
        httponly=True,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        **cookie_args,
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        httponly=True,
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,
        **cookie_args,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,
        **cookie_args,
    )


def clear_auth_cookies(response: Response) -> None:
    for cookie_name in (
        settings.access_cookie_name,
        settings.refresh_cookie_name,
        settings.csrf_cookie_name,
    ):
        response.delete_cookie(cookie_name, path="/")


def require_csrf(request: Request) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("X-CSRF-Token")
    if not cookie_token or not header_token or cookie_token != header_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_required", "message": "Valid CSRF token required."},
        )


def current_user_from_token(
    token: str,
    *,
    token_type: str,
    repo: IdentityRepository,
) -> UserRecord:
    try:
        payload = decode_token(token, secret_key=settings.jwt_secret_key, expected_type=token_type)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "Authentication token is invalid."},
        ) from exc

    user = repo.get_user_by_id(str(payload.get("sub", "")))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "inactive_user", "message": "User is inactive or does not exist."},
        )
    if int(payload.get("permission_version", -1)) != user.permission_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "stale_permissions", "message": "User permissions changed. Log in again."},
        )
    return user


def require_current_user(
    request: Request,
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserRecord:
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "auth_required", "message": "Authentication required."},
        )
    return current_user_from_token(token, token_type=ACCESS_TOKEN_TYPE, repo=repo)


def require_admin_user(
    request: Request,
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserRecord:
    user = require_current_user(request, repo)
    if not is_global_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "admin_required", "message": "System admin or platform admin account type required."},
        )
    require_csrf(request)
    return user


def require_platform_admin_user(
    request: Request,
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserRecord:
    user = require_current_user(request, repo)
    if not can_manage_workspace_config(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "platform_admin_required", "message": "Platform admin account type required."},
        )
    require_csrf(request)
    return user


def require_user_manager(
    request: Request,
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserRecord:
    user = require_current_user(request, repo)
    if not can_manage_users(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "user_manager_required", "message": "User management account type required."},
        )
    require_csrf(request)
    return user


def require_review_user(
    request: Request,
    repo: IdentityRepository = Depends(get_identity_repository),
) -> UserRecord:
    user = require_current_user(request, repo)
    if not can_review(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "reviewer_required", "message": "Reviewer account type required."},
        )
    require_csrf(request)
    return user
