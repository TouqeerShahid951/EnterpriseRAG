from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from rag.auth.routes.session import issue_login
from rag.auth.dependencies import require_current_user
from rag.auth.issued_tokens import create_auth_tokens
from rag.auth.refresh_sessions import InMemoryRefreshSessionStore, auth_idle_ttl_seconds
from rag.core.config import settings
from rag.auth.identity_models import UserRecord


class FakeIdentityRepository:
    def __init__(self, user: UserRecord) -> None:
        self.user = user

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self.user if user_id == self.user.id else None


class RecordingRefreshSessionStore:
    def __init__(self) -> None:
        self.remembered_ttl_seconds: int | None = None

    def remember(self, *, user_id: str, refresh_token: str, ttl_seconds: int) -> None:
        _ = user_id
        _ = refresh_token
        self.remembered_ttl_seconds = ttl_seconds

    def touch(self, *, user_id: str, refresh_token: str, ttl_seconds: int) -> bool:
        _ = user_id
        _ = refresh_token
        _ = ttl_seconds
        return True

    def rotate(self, *, user_id: str, old_token: str, new_token: str, ttl_seconds: int) -> bool:
        _ = user_id
        _ = old_token
        _ = new_token
        _ = ttl_seconds
        return True

    def revoke(self, refresh_token: str) -> None:
        _ = refresh_token

    def revoke_user(self, user_id: str) -> None:
        _ = user_id


def test_current_user_touches_active_refresh_session() -> None:
    user = _user()
    repo = FakeIdentityRepository(user)
    sessions = InMemoryRefreshSessionStore()
    access_token, refresh_token, _ = create_auth_tokens(user)
    sessions.remember(user_id=user.id, refresh_token=refresh_token, ttl_seconds=auth_idle_ttl_seconds())

    current = require_current_user(_request(access_token, refresh_token), repo, sessions)

    assert current.id == user.id


def test_current_user_rejects_idle_refresh_session() -> None:
    user = _user()
    repo = FakeIdentityRepository(user)
    sessions = InMemoryRefreshSessionStore()
    access_token, refresh_token, _ = create_auth_tokens(user)
    sessions.remember(user_id=user.id, refresh_token=refresh_token, ttl_seconds=-1)

    with pytest.raises(HTTPException) as exc_info:
        require_current_user(_request(access_token, refresh_token), repo, sessions)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "session_idle_timeout"


def test_current_user_requires_refresh_session_cookie() -> None:
    user = _user()
    repo = FakeIdentityRepository(user)
    sessions = InMemoryRefreshSessionStore()
    access_token, _refresh_token, _ = create_auth_tokens(user)

    with pytest.raises(HTTPException) as exc_info:
        require_current_user(_request(access_token, None), repo, sessions)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "refresh_required"


def test_login_stores_refresh_session_with_idle_ttl() -> None:
    user = _user()
    sessions = RecordingRefreshSessionStore()

    issue_login(Response(), user, sessions)

    assert sessions.remembered_ttl_seconds == auth_idle_ttl_seconds()


def _request(access_token: str, refresh_token: str | None) -> Request:
    cookies = [f"{settings.access_cookie_name}={access_token}"]
    if refresh_token is not None:
        cookies.append(f"{settings.refresh_cookie_name}={refresh_token}")
    return Request({
        "type": "http",
        "method": "GET",
        "headers": [(b"cookie", "; ".join(cookies).encode("ascii"))],
    })


def _user() -> UserRecord:
    user_id = str(uuid4())
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type="member",
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=("/finance",),
    )
