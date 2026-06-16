"""Auth token issuing helpers."""

from __future__ import annotations

from datetime import timedelta
from secrets import token_urlsafe

from ..core.config import settings
from ..repositories.identity import UserRecord
from .tokens import create_token

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def create_auth_tokens(user: UserRecord) -> tuple[str, str, str]:
    access_token = create_token(
        secret_key=settings.jwt_secret_key,
        subject=user.id,
        email=user.email,
        account_type=user.account_type,
        group_paths=list(user.group_paths),
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
        token_type=ACCESS_TOKEN_TYPE,
        ttl=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )
    refresh_token = create_token(
        secret_key=settings.jwt_secret_key,
        subject=user.id,
        email=user.email,
        account_type=user.account_type,
        group_paths=list(user.group_paths),
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
        token_type=REFRESH_TOKEN_TYPE,
        ttl=timedelta(days=settings.jwt_refresh_token_expire_days),
    )
    return access_token, refresh_token, token_urlsafe(32)
