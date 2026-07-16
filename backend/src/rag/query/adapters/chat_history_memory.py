"""In-memory chat history repository for tests and local fallback."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ..chat_history_models import ChatSessionRecord


class InMemoryChatHistoryRepository:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str, int], ChatSessionRecord] = {}

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

    def append_completed_turn(
        self,
        *,
        user_id: str,
        permission_version: int,
        session_id: str,
        title: str,
        user_turn: dict[str, Any],
        assistant_turn: dict[str, Any],
    ) -> ChatSessionRecord:
        key = (user_id, session_id, permission_version)
        now = datetime.now(UTC)
        current = self._sessions.get(key)
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
            session = replace(
                current,
                turns=(*current.turns, dict(user_turn), dict(assistant_turn)),
                updated_at=now,
            )
        self._sessions[key] = session
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
        return existed


def _question_count(turns: tuple[dict[str, Any], ...]) -> int:
    return sum(1 for turn in turns if turn.get("role") == "user")
