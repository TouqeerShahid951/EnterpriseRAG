from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest
from psycopg import sql

from rag.ingestion.adapters.job_postgres import PostgresIngestJobRepository
from rag.ingestion.delivery.schema import (
    INGEST_DELIVERY_SCHEMA_SQL,
    INGEST_DELIVERY_SCHEMA_VERSION,
    ensure_ingest_delivery_schema,
)


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def test_delivery_migration_runs_once_across_repeated_startups() -> None:
    connection = _RecordingConnection()

    assert ensure_ingest_delivery_schema(connection) is True
    assert ensure_ingest_delivery_schema(connection) is False

    assert connection.statements.count(INGEST_DELIVERY_SCHEMA_SQL) == 1
    assert connection.reserved_versions == {INGEST_DELIVERY_SCHEMA_VERSION}
    assert "UPDATE ingest_jobs" not in INGEST_DELIVERY_SCHEMA_SQL
    assert "ALTER COLUMN" not in INGEST_DELIVERY_SCHEMA_SQL
    assert "NOT VALID" in INGEST_DELIVERY_SCHEMA_SQL
    assert "VALIDATE CONSTRAINT" in INGEST_DELIVERY_SCHEMA_SQL


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL migration coverage",
)
def test_postgres_delivery_migration_initializes_legacy_rows_and_runs_twice() -> None:
    assert TEST_DATABASE_URL is not None
    repository = PostgresIngestJobRepository(TEST_DATABASE_URL)
    schema_name = f"test_ingest_delivery_{uuid4().hex}"

    with repository._connect() as conn:
        try:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            conn.execute(
                sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(schema_name)
                )
            )
            conn.execute(
                """
                CREATE TABLE ingest_jobs (
                    id UUID PRIMARY KEY,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO ingest_jobs (id, status, attempt_count)
                VALUES (%s, 'queued', 2), (%s, 'processing', 2)
                """,
                (str(uuid4()), str(uuid4())),
            )

            assert ensure_ingest_delivery_schema(conn) is True
            assert ensure_ingest_delivery_schema(conn) is False

            rows = conn.execute(
                """
                SELECT status, delivery_count, failure_attempt_count,
                       review_resume_count, resource_promotion_count
                FROM ingest_jobs
                ORDER BY status
                """
            ).fetchall()
            marker_count = conn.execute(
                "SELECT COUNT(*) AS count FROM ingest_delivery_schema_migrations"
            ).fetchone()["count"]
            nullable_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'ingest_jobs'
                  AND column_name IN (
                      'delivery_count', 'failure_attempt_count',
                      'review_resume_count', 'resource_promotion_count'
                  )
                  AND is_nullable = 'YES'
                """,
                (schema_name,),
            ).fetchone()["count"]

            assert [dict(row) for row in rows] == [
                {
                    "status": "processing",
                    "delivery_count": 0,
                    "failure_attempt_count": 0,
                    "review_resume_count": 0,
                    "resource_promotion_count": 0,
                },
                {
                    "status": "queued",
                    "delivery_count": 0,
                    "failure_attempt_count": 0,
                    "review_resume_count": 0,
                    "resource_promotion_count": 0,
                },
            ]
            assert marker_count == 1
            assert nullable_count == 0
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


class _Result:
    def __init__(self, row: dict[str, int] | None = None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, int] | None:
        return self._row


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.reserved_versions: set[int] = set()

    def execute(
        self,
        statement: str,
        params: tuple[Any, ...] = (),
    ) -> _Result:
        self.statements.append(statement)
        if "INSERT INTO ingest_delivery_schema_migrations" not in statement:
            return _Result()
        version = int(params[0])
        if version in self.reserved_versions:
            return _Result()
        self.reserved_versions.add(version)
        return _Result({"version": version})

    @contextmanager
    def transaction(self):
        yield
