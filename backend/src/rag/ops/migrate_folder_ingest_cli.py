"""Idempotent local schema migration for scheduled folder ingestion."""

from __future__ import annotations

from rag.core.config import settings
from rag.repositories.postgres import PostgresConnectionMixin


MIGRATION_SQL = """
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_ingest_status_known;
ALTER TABLE documents ADD CONSTRAINT documents_ingest_status_known CHECK (
    ingest_status IN ('scheduled', 'queued', 'processing', 'complete', 'failed', 'human_review')
);

ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_status_known;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_status_known CHECK (
    status IN ('scheduled', 'queued', 'processing', 'complete', 'failed', 'human_review')
);

CREATE TABLE IF NOT EXISTS folder_ingest_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    group_path TEXT NOT NULL REFERENCES groups(path) ON UPDATE CASCADE ON DELETE RESTRICT,
    doc_type TEXT NOT NULL,
    effective_date DATE NULL,
    expiry_date DATE NULL,
    description TEXT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Karachi',
    scheduled_at TIMESTAMPTZ NULL,
    recurrence JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    last_run_at TIMESTAMPTZ NULL,
    next_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT folder_ingest_schedules_name_not_blank CHECK (length(btrim(name)) > 0),
    CONSTRAINT folder_ingest_schedules_source_type_known CHECK (source_type IN ('snapshot', 'minio_prefix')),
    CONSTRAINT folder_ingest_schedules_schedule_type_known CHECK (schedule_type IN ('one_time', 'recurring')),
    CONSTRAINT folder_ingest_schedules_status_known CHECK (status IN ('scheduled', 'active', 'paused', 'cancelled', 'complete', 'failed')),
    CONSTRAINT folder_ingest_schedules_recurrence_object CHECK (jsonb_typeof(recurrence) = 'object'),
    CONSTRAINT folder_ingest_schedules_source_config_object CHECK (jsonb_typeof(source_config) = 'object'),
    CONSTRAINT folder_ingest_schedules_expiry_after_effective CHECK (
        expiry_date IS NULL OR expiry_date >= effective_date
    )
);

CREATE INDEX IF NOT EXISTS folder_ingest_schedules_next_run_idx
    ON folder_ingest_schedules (status, next_run_at)
    WHERE next_run_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS folder_ingest_schedules_group_path_idx ON folder_ingest_schedules (group_path);

CREATE TABLE IF NOT EXISTS folder_ingest_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID NOT NULL REFERENCES folder_ingest_schedules(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'scheduled',
    due_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    error_code TEXT NULL,
    error_message_safe TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT folder_ingest_runs_status_known CHECK (status IN ('scheduled', 'running', 'complete', 'failed', 'cancelled')),
    CONSTRAINT folder_ingest_runs_completed_after_started CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    )
);

CREATE INDEX IF NOT EXISTS folder_ingest_runs_schedule_idx ON folder_ingest_runs (schedule_id, created_at DESC);

CREATE TABLE IF NOT EXISTS folder_ingest_run_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES folder_ingest_runs(id) ON DELETE CASCADE,
    schedule_id UUID NOT NULL REFERENCES folder_ingest_schedules(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    object_path TEXT NULL,
    content_hash TEXT NULL,
    size_bytes BIGINT NULL,
    content_type TEXT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    skip_code TEXT NULL,
    skip_message TEXT NULL,
    document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
    job_id UUID NULL REFERENCES ingest_jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT folder_ingest_run_items_source_path_not_blank CHECK (length(btrim(source_path)) > 0),
    CONSTRAINT folder_ingest_run_items_filename_not_blank CHECK (length(btrim(filename)) > 0),
    CONSTRAINT folder_ingest_run_items_status_known CHECK (status IN ('scheduled', 'queued', 'skipped', 'failed'))
);

CREATE INDEX IF NOT EXISTS folder_ingest_run_items_run_idx ON folder_ingest_run_items (run_id, created_at);
CREATE INDEX IF NOT EXISTS folder_ingest_run_items_source_idx ON folder_ingest_run_items (schedule_id, source_path, created_at DESC);
CREATE INDEX IF NOT EXISTS folder_ingest_run_items_document_idx ON folder_ingest_run_items (document_id) WHERE document_id IS NOT NULL;

ALTER TABLE folder_ingest_schedules ALTER COLUMN effective_date DROP NOT NULL;
"""


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        conn.execute(MIGRATION_SQL)
    print("Folder ingestion schema migration complete.")


if __name__ == "__main__":
    main()
