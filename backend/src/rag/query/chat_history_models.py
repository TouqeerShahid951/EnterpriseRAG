"""Chat history repository contracts and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ChatSessionRecord:
    id: str
    user_id: str
    permission_version: int
    title: str
    turns: tuple[dict[str, Any], ...]
    created_at: datetime | None
    updated_at: datetime | None
    question_count: int | None = None


class ChatHistoryRepository(Protocol):
    def list_sessions_page(
        self,
        *,
        user_id: str,
        permission_version: int,
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[ChatSessionRecord], int]: ...
    def list_sessions(self, *, user_id: str, permission_version: int, limit: int = 30, offset: int = 0) -> list[ChatSessionRecord]: ...
    def count_sessions(self, *, user_id: str, permission_version: int) -> int: ...
    def get_session(self, *, session_id: str, user_id: str, permission_version: int) -> ChatSessionRecord | None: ...
    def append_completed_turn(
        self,
        *,
        user_id: str,
        permission_version: int,
        session_id: str,
        title: str,
        user_turn: dict[str, Any],
        assistant_turn: dict[str, Any],
    ) -> ChatSessionRecord: ...
    def update_assistant_response(
        self,
        *,
        user_id: str,
        permission_version: int,
        session_id: str,
        trace_id: str,
        response: dict[str, Any],
    ) -> bool: ...
    def delete_session(self, *, session_id: str, user_id: str, permission_version: int) -> bool: ...
