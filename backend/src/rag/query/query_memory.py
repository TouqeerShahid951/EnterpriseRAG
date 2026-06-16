"""Session memory store for query turns."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Protocol

from ..auth.context import UserContext
from ..core.config import settings

QueryTurn = dict[str, object]


class QuerySessionStore(Protocol):
    def load(self, *, user: UserContext, session_id: str) -> list[QueryTurn]: ...
    def append(self, *, user: UserContext, session_id: str, turn: QueryTurn, ttl_seconds: int) -> None: ...


class InMemoryQuerySessionStore:
    def __init__(self) -> None:
        self._turns: dict[str, list[QueryTurn]] = {}

    def load(self, *, user: UserContext, session_id: str) -> list[QueryTurn]:
        return list(self._turns.get(_session_key(user, session_id), []))

    def append(self, *, user: UserContext, session_id: str, turn: QueryTurn, ttl_seconds: int) -> None:
        _ = ttl_seconds
        key = _session_key(user, session_id)
        self._turns[key] = [*self._turns.get(key, []), turn][-8:]


class RedisQuerySessionStore:
    def __init__(self, redis_url: str, prefix: str) -> None:
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError("redis package is required for Redis query sessions") from exc
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix

    def load(self, *, user: UserContext, session_id: str) -> list[QueryTurn]:
        raw = self._client.get(self._key(user, session_id))
        if raw is None:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("stored query session was not valid JSON") from exc
        if not isinstance(value, list):
            raise RuntimeError("stored query session had invalid shape")
        return [turn for turn in value if isinstance(turn, dict)]

    def append(self, *, user: UserContext, session_id: str, turn: QueryTurn, ttl_seconds: int) -> None:
        turns = [*self.load(user=user, session_id=session_id), turn][-8:]
        self._client.setex(self._key(user, session_id), ttl_seconds, json.dumps(turns))

    def _key(self, user: UserContext, session_id: str) -> str:
        return f"{self._prefix}:{_session_key(user, session_id)}"


@lru_cache
def default_query_session_store() -> QuerySessionStore:
    if settings.rag_session_store == "memory":
        return InMemoryQuerySessionStore()
    if settings.rag_session_store != "redis":
        raise RuntimeError(f"unsupported query session store: {settings.rag_session_store}")
    return RedisQuerySessionStore(settings.redis_url, settings.rag_session_prefix)


def _session_key(user: UserContext, session_id: str) -> str:
    return f"{user.user_id}:{user.permission_version}:{session_id}"
