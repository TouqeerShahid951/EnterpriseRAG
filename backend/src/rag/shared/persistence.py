"""Shared PostgreSQL helpers for repository adapters."""

from __future__ import annotations

import atexit
import os
from threading import Lock
from typing import Any


_POOL_LOCK = Lock()
_POOLS: dict[str, Any] = {}
_POOL_PROCESS_ID = os.getpid()


class PostgresConnectionMixin:
    database_url: str

    def _connect(self):
        return _postgres_pool(self.database_url).connection()

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


def close_postgres_pools() -> None:
    with _POOL_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close()


def _postgres_pool(database_url: str):
    global _POOL_PROCESS_ID
    process_id = os.getpid()
    with _POOL_LOCK:
        if process_id != _POOL_PROCESS_ID:
            # ponytail: forked workers create their own small pool on first use.
            _POOLS.clear()
            _POOL_PROCESS_ID = process_id
        pool = _POOLS.get(database_url)
        if pool is None:
            pool = _create_postgres_pool(database_url)
            _POOLS[database_url] = pool
        return pool


def _create_postgres_pool(database_url: str):
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "psycopg and psycopg-pool are required for postgres repositories"
        ) from exc
    return ConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=5,
        timeout=5,
        kwargs={"row_factory": dict_row},
    )


atexit.register(close_postgres_pools)
