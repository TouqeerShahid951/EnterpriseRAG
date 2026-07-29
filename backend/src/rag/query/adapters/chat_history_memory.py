"""In-memory chat history repository for tests and local fallback."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ..chat_history_models import (
    ChatHistoryRequestConflict,
    ChatSessionRecord,
    context_turns_from_payloads,
)


class InMemoryChatHistoryRepository:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str, int], ChatSessionRecord] = {}
        self._request_fingerprints: dict[tuple[str, str, int, str], str | None] = {}
        self._request_assistant_indexes: dict[tuple[str, str, int, str], int] = {}

    def list_sessions_page(
        self,
        *,
        user_id: str,
        permission_version: int,
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[ChatSessionRecord], int]:
        sessions = [
            session
            for (session_user_id, _session_id, session_permission_version), session in self._sessions.items()
            if session_user_id == user_id and session_permission_version == permission_version
        ]
        sorted_sessions = sorted(
            sessions,
            key=lambda session: session.updated_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        page = [
            replace(session, turns=(), question_count=_question_count(session.turns))
            for session in sorted_sessions[offset:offset + limit]
        ]
        return page, len(sorted_sessions)

    def list_sessions(self, *, user_id: str, permission_version: int, limit: int = 30, offset: int = 0) -> list[ChatSessionRecord]:
        sessions, _ = self.list_sessions_page(
            user_id=user_id,
            permission_version=permission_version,
            limit=limit,
            offset=offset,
        )
        return sessions

    def count_sessions(self, *, user_id: str, permission_version: int) -> int:
        return sum(
            1
            for session_user_id, _session_id, session_permission_version in self._sessions
            if session_user_id == user_id and session_permission_version == permission_version
        )

    def get_session(self, *, session_id: str, user_id: str, permission_version: int) -> ChatSessionRecord | None:
        return self._sessions.get((user_id, session_id, permission_version))

    def load_recent_context_turns(
        self,
        *,
        session_id: str,
        user_id: str,
        permission_version: int,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        session = self.get_session(
            session_id=session_id,
            user_id=user_id,
            permission_version=permission_version,
        )
        if session is None:
            return []
        return context_turns_from_payloads(session.turns, limit=limit)

    def append_completed_turn(
        self,
        *,
        user_id: str,
        permission_version: int,
        session_id: str,
        title: str,
        user_turn: dict[str, Any],
        assistant_turn: dict[str, Any],
        client_request_id: str | None = None,
        request_fingerprint: str | None = None,
    ) -> ChatSessionRecord:
        key = (user_id, session_id, permission_version)
        request_key = (
            (user_id, session_id, permission_version, client_request_id)
            if client_request_id is not None
            else None
        )
        now = datetime.now(UTC)
        current = self._sessions.get(key)
        if request_key is not None and request_key in self._request_assistant_indexes:
            if self._request_fingerprints[request_key] != request_fingerprint:
                raise ChatHistoryRequestConflict(
                    "client_request_id was already used for a different query request"
                )
            if current is None:
                raise RuntimeError("saved chat request referenced a missing session")
            turns = list(current.turns)
            turns[self._request_assistant_indexes[request_key]] = dict(assistant_turn)
            session = replace(current, turns=tuple(turns), updated_at=now)
            self._sessions[key] = session
            return session
        if current is None:
            session = ChatSessionRecord(
                id=session_id,
                user_id=user_id,
                permission_version=permission_version,
                title=title,
                turns=(dict(user_turn), dict(assistant_turn)),
                created_at=now,
                updated_at=now,
            )
        else:
            assistant_index = len(current.turns) + 1
            session = replace(
                current,
                turns=(*current.turns, dict(user_turn), dict(assistant_turn)),
                updated_at=now,
            )
        if current is None:
            assistant_index = 1
        self._sessions[key] = session
        if request_key is not None:
            self._request_fingerprints[request_key] = request_fingerprint
            self._request_assistant_indexes[request_key] = assistant_index
        return session

    def update_assistant_response(
        self,
        *,
        user_id: str,
        permission_version: int,
        session_id: str,
        trace_id: str,
        response: dict[str, Any],
    ) -> bool:
        key = (user_id, session_id, permission_version)
        current = self._sessions.get(key)
        if current is None:
            return False
        updated = False
        turns: list[dict[str, Any]] = []
        for turn in current.turns:
            next_turn = dict(turn)
            existing = next_turn.get("response")
            if (
                not updated
                and next_turn.get("role") == "assistant"
                and isinstance(existing, dict)
                and existing.get("trace_id") == trace_id
            ):
                next_turn["response"] = dict(response)
                updated = True
            turns.append(next_turn)
        if not updated:
            return False
        self._sessions[key] = replace(current, turns=tuple(turns), updated_at=datetime.now(UTC))
        return True

    def delete_session(self, *, session_id: str, user_id: str, permission_version: int) -> bool:
        key = (user_id, session_id, permission_version)
        existed = key in self._sessions
        self._sessions.pop(key, None)
        for request_key in [
            candidate
            for candidate in self._request_fingerprints
            if candidate[:3] == key
        ]:
            self._request_fingerprints.pop(request_key, None)
            self._request_assistant_indexes.pop(request_key, None)
        return existed


def _question_count(turns: tuple[dict[str, Any], ...]) -> int:
    return sum(1 for turn in turns if turn.get("role") == "user")
