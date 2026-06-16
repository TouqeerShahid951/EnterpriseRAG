"""Idempotent schema migration for ingestion parser provenance."""

from __future__ import annotations

from rag.core.config import settings
from rag.repositories.postgres import PostgresConnectionMixin


DDL = """
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS parser_provenance JSONB NULL;
ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_parser_provenance_object;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_parser_provenance_object CHECK (
    parser_provenance IS NULL OR jsonb_typeof(parser_provenance) = 'object'
);
"""


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        conn.execute(DDL)
    print("Parser provenance schema migration complete.")


if __name__ == "__main__":
    main()
