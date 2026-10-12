"""Idempotent schema for checkpoint references."""

from __future__ import annotations

from typing import Any


INGEST_CHECKPOINT_SCHEMA_VERSION = 1

INGEST_CHECKPOINT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingest_checkpoints (
    job_id UUID NOT NULL REFERENCES ingest_jobs(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    stage_key TEXT NOT NULL,
    object_key TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    body_sha256 TEXT NOT NULL,
    compressed_size INTEGER NOT NULL,
    decoded_size INTEGER NOT NULL,
    upstream_sha256 TEXT NOT NULL,
    configuration_digest TEXT NOT NULL,
    range_start INTEGER NULL,
    range_end INTEGER NULL,
    model_identity TEXT NULL,
    vector_dimension INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id, stage_key),
    CONSTRAINT ingest_checkpoints_key_nonempty CHECK (length(stage_key) > 0),
    CONSTRAINT ingest_checkpoints_sizes_valid CHECK (compressed_size > 0 AND decoded_size > 0),
    CONSTRAINT ingest_checkpoints_range_valid CHECK (
        (range_start IS NULL AND range_end IS NULL)
        OR (range_start >= 0 AND range_end > range_start)
    ),
    CONSTRAINT ingest_checkpoints_document_job_unique UNIQUE (job_id, document_id, stage_key)
)
"""


def ensure_ingest_checkpoint_schema(conn: Any) -> None:
    conn.execute(INGEST_CHECKPOINT_SCHEMA_SQL)

