"""Idempotent local schema migration for richer ingest progress details."""

from __future__ import annotations

from rag.core.config import settings
from rag.shared.persistence import PostgresConnectionMixin


DDL = """
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS stage_progress JSONB NULL;
ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_stage_progress_object;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_stage_progress_object CHECK (
    stage_progress IS NULL OR jsonb_typeof(stage_progress) = 'object'
);
"""


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        conn.execute(DDL)
    print("Ingest progress schema migration complete.")


if __name__ == "__main__":
    main()
