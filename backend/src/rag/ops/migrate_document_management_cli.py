"""Idempotent schema migration for document management workflows."""

from __future__ import annotations

from rag.core.config import settings
from rag.shared.persistence import PostgresConnectionMixin


MIGRATION_SQL = """
WITH ranked_active_jobs AS (
    SELECT
        id,
        row_number() OVER (PARTITION BY doc_id ORDER BY created_at DESC, id DESC) AS active_rank
    FROM ingest_jobs
    WHERE status IN ('scheduled', 'queued', 'processing', 'human_review')
)
UPDATE ingest_jobs
SET status = 'failed',
    error_code = COALESCE(error_code, 'duplicate_active_job_migrated'),
    error_message_safe = COALESCE(error_message_safe, 'Superseded by a newer active ingest job during document-management migration.'),
    completed_at = COALESCE(completed_at, NOW()),
    updated_at = NOW()
WHERE id IN (
    SELECT id FROM ranked_active_jobs WHERE active_rank > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS ingest_jobs_one_active_per_doc_uidx
    ON ingest_jobs (doc_id)
    WHERE status IN ('scheduled', 'queued', 'processing', 'human_review');
"""


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        conn.execute(MIGRATION_SQL)
    print("Document management schema migration complete.")


if __name__ == "__main__":
    main()
