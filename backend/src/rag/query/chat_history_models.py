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


class ChatHistoryRequestConflict(ValueError):
    """A client request id was reused for a different query request."""


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
    def load_recent_context_turns(
        self,
        *,
        session_id: str,
        user_id: str,
        permission_version: int,
        limit: int = 8,
    ) -> list[dict[str, object]]: ...
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


def context_turns_from_payloads(
    payloads: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    """Project saved UI turns into bounded complete query exchanges."""

    if limit <= 0:
        return []
    exchanges: list[dict[str, object]] = []
    pending_user: dict[str, Any] | None = None
    for payload in payloads:
        role = payload.get("role")
        if role == "user":
            pending_user = payload
            continue
        if role != "assistant" or pending_user is None:
            continue
        response = payload.get("response")
        if not isinstance(response, dict):
            pending_user = None
            continue
        query = pending_user.get("content")
        answer = response.get("answer")
        if isinstance(query, str) and query.strip() and isinstance(answer, str):
            sources = response.get("sources")
            exchange: dict[str, object] = {
                "query": query.strip(),
                "answer": answer,
                "intent": response.get("intent"),
                "sources": sources if isinstance(sources, list) else [],
                "source_mode": response.get("source_mode"),
                "source_decision_reason": response.get("source_decision_reason"),
                "group_path": payload.get("groupPath"),
                "document_ids": payload.get("documentIds") or [],
                "query_source_id": payload.get("querySourceId"),
                "faithfulness_score": response.get("faithfulness_score"),
                "faithfulness_status": response.get("faithfulness_status"),
                "degraded": response.get("degraded"),
            }
            turn_id = pending_user.get("id")
            if isinstance(turn_id, str) and turn_id.strip():
                exchange["turn_id"] = turn_id.strip()
            exchanges.append(exchange)
        pending_user = None
    return exchanges[-limit:]
