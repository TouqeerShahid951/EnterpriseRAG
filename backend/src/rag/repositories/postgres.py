"""Shared PostgreSQL helpers for repository adapters."""

from __future__ import annotations

from typing import Any


class PostgresConnectionMixin:
    database_url: str

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for postgres repositories") from exc
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _execute_one(self, query: str, params: tuple[Any, ...]) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if row is None:
            raise RuntimeError("repository query unexpectedly returned no row")
        return row

    def _execute_optional(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute(query, params).fetchone()

    def _execute_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return list(conn.execute(query, params).fetchall())
