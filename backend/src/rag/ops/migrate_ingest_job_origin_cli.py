"""Idempotent migration for ingestion job origins."""

from __future__ import annotations

from rag.core.config import settings
from rag.shared.persistence import PostgresConnectionMixin


MIGRATION_SQL = """
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'unknown';

UPDATE ingest_jobs
SET origin = 'folder'
WHERE origin = 'unknown'
  AND id IN (
      SELECT job_id
      FROM folder_ingest_run_items
      WHERE job_id IS NOT NULL
  );

UPDATE ingest_jobs AS jobs
SET origin = CASE audit.event_type
    WHEN 'upload.queued' THEN 'upload'
    WHEN 'documents.reingest' THEN 'reingest'
    WHEN 'documents.restore' THEN 'restore'
    ELSE jobs.origin
END
FROM audit_log AS audit
WHERE jobs.origin = 'unknown'
  AND audit.payload->>'job_id' = jobs.id::text
  AND audit.event_type IN ('upload.queued', 'documents.reingest', 'documents.restore');

UPDATE ingest_jobs
SET origin = 'unknown'
WHERE origin NOT IN ('upload', 'reingest', 'restore', 'folder', 'connector', 'unknown') OR origin IS NULL;

ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_origin_known;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_origin_known CHECK (
    origin IN ('upload', 'reingest', 'restore', 'folder', 'connector', 'unknown')
);
"""


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        conn.execute(MIGRATION_SQL)
    print("Ingestion job origin migration complete.")


if __name__ == "__main__":
    main()
