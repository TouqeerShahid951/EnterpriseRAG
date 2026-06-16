"""Refresh-token session persistence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol

from ..core.config import settings


class RefreshSessionStore(Protocol):
    def remember(self, *, user_id: str, refresh_token: str, ttl_seconds: int) -> None: ...
    def rotate(self, *, user_id: str, old_token: str, new_token: str, ttl_seconds: int) -> bool: ...
    def revoke(self, refresh_token: str) -> None: ...


class InMemoryRefreshSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, tuple[str, datetime]] = {}

    def remember(self, *, user_id: str, refresh_token: str, ttl_seconds: int) -> None:
        self._sessions[_digest(refresh_token)] = (user_id, _expires_at(ttl_seconds))

    def rotate(self, *, user_id: str, old_token: str, new_token: str, ttl_seconds: int) -> bool:
        old_key = _digest(old_token)
        stored = self._sessions.pop(old_key, None)
        if stored is None or stored[0] != user_id or stored[1] <= datetime.now(UTC):
            return False
        self.remember(user_id=user_id, refresh_token=new_token, ttl_seconds=ttl_seconds)
        return True

    def revoke(self, refresh_token: str) -> None:
        self._sessions.pop(_digest(refresh_token), None)


class RedisRefreshSessionStore:
    def __init__(self, redis_url: str, prefix: str) -> None:
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError("redis package is required for Redis refresh sessions") from exc
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix

    def remember(self, *, user_id: str, refresh_token: str, ttl_seconds: int) -> None:
        self._client.setex(self._key(refresh_token), ttl_seconds, user_id)

    def rotate(self, *, user_id: str, old_token: str, new_token: str, ttl_seconds: int) -> bool:
        old_owner = self._client.getdel(self._key(old_token))
        if old_owner != user_id:
            return False
        self.remember(user_id=user_id, refresh_token=new_token, ttl_seconds=ttl_seconds)
        return True

    def revoke(self, refresh_token: str) -> None:
        self._client.delete(self._key(refresh_token))

    def _key(self, refresh_token: str) -> str:
        return f"{self._prefix}:{_digest(refresh_token)}"


def refresh_ttl_seconds() -> int:
    return int(timedelta(days=settings.jwt_refresh_token_expire_days).total_seconds())


@lru_cache
def default_refresh_session_store() -> RefreshSessionStore:
    if settings.refresh_session_store == "memory":
        return InMemoryRefreshSessionStore()
    if settings.refresh_session_store != "redis":
        raise RuntimeError(f"unsupported refresh session store: {settings.refresh_session_store}")
    return RedisRefreshSessionStore(settings.redis_url, settings.refresh_session_prefix)


def get_refresh_session_store() -> RefreshSessionStore:
    return default_refresh_session_store()


def _digest(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _expires_at(ttl_seconds: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=ttl_seconds)
