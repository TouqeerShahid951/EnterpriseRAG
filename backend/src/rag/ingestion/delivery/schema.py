"""PostgreSQL schema for durable ingestion delivery."""

from __future__ import annotations

from typing import Any


INGEST_DELIVERY_SCHEMA_VERSION = 1

_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ingest_delivery_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ingest_delivery_schema_migrations_version_positive
        CHECK (version > 0)
)
"""

_RESERVE_MIGRATION_SQL = """
INSERT INTO ingest_delivery_schema_migrations (version)
VALUES (%s)
ON CONFLICT (version) DO NOTHING
RETURNING version
"""

INGEST_DELIVERY_SCHEMA_SQL = """
ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS delivery_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS failure_attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS review_resume_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS resource_promotion_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS active_delivery_id UUID NULL;
ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS last_failure_run_token TEXT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ingest_jobs'::regclass
          AND conname = 'ingest_jobs_delivery_counters_nonnegative'
    ) THEN
        ALTER TABLE ingest_jobs
            ADD CONSTRAINT ingest_jobs_delivery_counters_nonnegative CHECK (
                delivery_count >= 0
                AND failure_attempt_count >= 0
                AND review_resume_count >= 0
                AND resource_promotion_count >= 0
            ) NOT VALID;
    END IF;
END $$;
ALTER TABLE ingest_jobs
    VALIDATE CONSTRAINT ingest_jobs_delivery_counters_nonnegative;

CREATE TABLE IF NOT EXISTS ingest_outbox (
    delivery_id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES ingest_jobs(id) ON DELETE CASCADE,
    event_kind TEXT NOT NULL,
    payload JSONB NOT NULL,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claim_token TEXT NULL,
    claim_expires_at TIMESTAMPTZ NULL,
    publish_attempt_count INTEGER NOT NULL DEFAULT 0,
    published_at TIMESTAMPTZ NULL,
    last_error_code TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ingest_outbox_event_kind_not_blank
        CHECK (length(btrim(event_kind)) BETWEEN 1 AND 100),
    CONSTRAINT ingest_outbox_payload_object
        CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT ingest_outbox_payload_delivery_matches
        CHECK (payload ->> 'delivery_id' = delivery_id::text),
    CONSTRAINT ingest_outbox_payload_job_matches
        CHECK (payload ->> 'job_id' = job_id::text),
    CONSTRAINT ingest_outbox_publish_attempt_count_nonnegative
        CHECK (publish_attempt_count >= 0),
    CONSTRAINT ingest_outbox_claim_complete
        CHECK ((claim_token IS NULL) = (claim_expires_at IS NULL)),
    CONSTRAINT ingest_outbox_published_not_claimed
        CHECK (published_at IS NULL OR claim_token IS NULL)
);

CREATE INDEX IF NOT EXISTS ingest_outbox_pending_idx
    ON ingest_outbox (available_at, created_at, delivery_id)
    WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS ingest_outbox_job_idx
    ON ingest_outbox (job_id, created_at DESC);
"""


def ensure_ingest_delivery_schema(conn: Any) -> bool:
    """Apply the versioned delivery migration once on this database."""
    conn.execute(_MIGRATION_TABLE_SQL)
    with conn.transaction():
        reserved = conn.execute(
            _RESERVE_MIGRATION_SQL,
            (INGEST_DELIVERY_SCHEMA_VERSION,),
        ).fetchone()
        if reserved is None:
            return False
        conn.execute(INGEST_DELIVERY_SCHEMA_SQL)
    return True


__all__ = [
    "INGEST_DELIVERY_SCHEMA_SQL",
    "INGEST_DELIVERY_SCHEMA_VERSION",
    "ensure_ingest_delivery_schema",
]
