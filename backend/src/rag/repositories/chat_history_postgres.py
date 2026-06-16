"""PostgreSQL chat history repository."""

from __future__ import annotations

import json
from typing import Any

from .chat_history_models import ChatSessionRecord
from .postgres import PostgresConnectionMixin


class PostgresChatHistoryRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._ensure_tables()

    def list_sessions(self, *, user_id: str, permission_version: int, limit: int = 30) -> list[ChatSessionRecord]:
        rows = self._execute_all(
            """
            SELECT s.*, COALESCE(
                jsonb_agg(t.payload ORDER BY t.turn_index) FILTER (WHERE t.turn_index IS NOT NULL),
                '[]'::jsonb
            ) AS turns
            FROM chat_sessions s
            LEFT JOIN chat_session_turns t
              ON t.session_id = s.id
             AND t.user_id = s.user_id
             AND t.permission_version = s.permission_version
            WHERE s.user_id = %s AND s.permission_version = %s
            GROUP BY s.id, s.user_id, s.permission_version
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT %s
            """,
            (user_id, permission_version, limit),
        )
        return [session_from_row(row) for row in rows]

    def get_session(self, *, session_id: str, user_id: str, permission_version: int) -> ChatSessionRecord | None:
        row = self._execute_optional(
            """
            SELECT s.*, COALESCE(
                jsonb_agg(t.payload ORDER BY t.turn_index) FILTER (WHERE t.turn_index IS NOT NULL),
                '[]'::jsonb
            ) AS turns
            FROM chat_sessions s
            LEFT JOIN chat_session_turns t
              ON t.session_id = s.id
             AND t.user_id = s.user_id
             AND t.permission_version = s.permission_version
            WHERE s.id = %s AND s.user_id = %s AND s.permission_version = %s
            GROUP BY s.id, s.user_id, s.permission_version
            """,
            (session_id, user_id, permission_version),
        )
        return session_from_row(row) if row else None

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
        with self._connect() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO chat_sessions (id, user_id, permission_version, title)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id, user_id, permission_version) DO UPDATE
                    SET updated_at = NOW()
                    """,
                    (session_id, user_id, permission_version, title),
                )
                row = conn.execute(
                    """
                    SELECT COALESCE(MAX(turn_index), -1) AS last_index
                    FROM chat_session_turns
                    WHERE session_id = %s AND user_id = %s AND permission_version = %s
                    """,
                    (session_id, user_id, permission_version),
                ).fetchone()
                turn_index = int(row["last_index"]) + 1
                conn.execute(
                    """
                    INSERT INTO chat_session_turns (
                        session_id, user_id, permission_version, turn_index, role, payload
                    )
                    VALUES (%s, %s, %s, %s, 'user', %s::jsonb),
                           (%s, %s, %s, %s, 'assistant', %s::jsonb)
                    """,
                    (
                        session_id,
                        user_id,
                        permission_version,
                        turn_index,
                        json.dumps(user_turn),
                        session_id,
                        user_id,
                        permission_version,
                        turn_index + 1,
                        json.dumps(assistant_turn),
                    ),
                )
                conn.execute(
                    """
                    UPDATE chat_sessions
                    SET updated_at = NOW()
                    WHERE id = %s AND user_id = %s AND permission_version = %s
                    """,
                    (session_id, user_id, permission_version),
                )
        session = self.get_session(session_id=session_id, user_id=user_id, permission_version=permission_version)
        if session is None:
            raise RuntimeError("saved chat session could not be reloaded")
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
        with self._connect() as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    UPDATE chat_session_turns
                    SET payload = jsonb_set(payload, '{response}', %s::jsonb, true)
                    WHERE session_id = %s
                      AND user_id = %s
                      AND permission_version = %s
                      AND role = 'assistant'
                      AND payload->'response'->>'trace_id' = %s
                    """,
                    (json.dumps(response), session_id, user_id, permission_version, trace_id),
                )
                if result.rowcount:
                    conn.execute(
                        """
                        UPDATE chat_sessions
                        SET updated_at = NOW()
                        WHERE id = %s AND user_id = %s AND permission_version = %s
                        """,
                        (session_id, user_id, permission_version),
                    )
                return result.rowcount > 0

    def delete_session(self, *, session_id: str, user_id: str, permission_version: int) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM chat_sessions
                WHERE id = %s AND user_id = %s AND permission_version = %s
                """,
                (session_id, user_id, permission_version),
            )
            return result.rowcount > 0

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(CHAT_HISTORY_SCHEMA_SQL)


def session_from_row(row: dict[str, Any]) -> ChatSessionRecord:
    turns = row.get("turns") or []
    if isinstance(turns, str):
        turns = json.loads(turns)
    return ChatSessionRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        permission_version=int(row["permission_version"]),
        title=str(row["title"]),
        turns=tuple(turn for turn in turns if isinstance(turn, dict)),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


CHAT_HISTORY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission_version INTEGER NOT NULL,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, user_id, permission_version),
    CONSTRAINT chat_sessions_id_not_blank CHECK (length(btrim(id)) > 0),
    CONSTRAINT chat_sessions_title_not_blank CHECK (length(btrim(title)) > 0),
    CONSTRAINT chat_sessions_permission_version_positive CHECK (permission_version >= 0)
);

CREATE INDEX IF NOT EXISTS chat_sessions_user_updated_idx
    ON chat_sessions (user_id, permission_version, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_session_turns (
    session_id TEXT NOT NULL,
    user_id UUID NOT NULL,
    permission_version INTEGER NOT NULL,
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, user_id, permission_version, turn_index),
    FOREIGN KEY (session_id, user_id, permission_version)
        REFERENCES chat_sessions(id, user_id, permission_version)
        ON DELETE CASCADE,
    CONSTRAINT chat_session_turns_index_nonnegative CHECK (turn_index >= 0),
    CONSTRAINT chat_session_turns_role_known CHECK (role IN ('user', 'assistant')),
    CONSTRAINT chat_session_turns_payload_object CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS chat_session_turns_session_idx
    ON chat_session_turns (session_id, user_id, permission_version, turn_index);
"""
