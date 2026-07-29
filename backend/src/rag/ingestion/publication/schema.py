"""PostgreSQL schema for generation-safe document index publication."""

from __future__ import annotations

from typing import Any


INGEST_PUBLICATION_SCHEMA_VERSION = 2

_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ingest_publication_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ingest_publication_schema_migrations_version_positive CHECK (version > 0)
)
"""

_RESERVE_MIGRATION_SQL = """
INSERT INTO ingest_publication_schema_migrations (version)
VALUES (%s)
ON CONFLICT (version) DO NOTHING
RETURNING version
"""

INGEST_PUBLICATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS document_index_generations (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    job_id UUID NOT NULL UNIQUE REFERENCES ingest_jobs(id) ON DELETE CASCADE,
    input_hash TEXT NOT NULL,
    configuration_digest TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'building',
    expected_point_count INTEGER NOT NULL,
    expected_item_hash TEXT NOT NULL,
    vector_dimension INTEGER NOT NULL,
    staged_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    activated_at TIMESTAMPTZ NULL,
    retired_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT document_index_generations_state_known CHECK (
        state IN ('building', 'verified', 'active', 'retiring', 'retired', 'failed')
    ),
    CONSTRAINT document_index_generations_expected_count_nonnegative CHECK (expected_point_count >= 0),
    CONSTRAINT document_index_generations_vector_dimension_nonnegative CHECK (vector_dimension >= 0),
    CONSTRAINT document_index_generations_input_hash_format CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT document_index_generations_configuration_digest_format CHECK (
        configuration_digest ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT document_index_generations_expected_item_hash_format CHECK (
        expected_item_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT document_index_generations_staged_metadata_object CHECK (
        jsonb_typeof(staged_metadata) = 'object'
    ),
    CONSTRAINT document_index_generations_id_document_unique UNIQUE (id, document_id)
);

ALTER TABLE document_index_generations
    DROP CONSTRAINT IF EXISTS document_index_generations_expected_count_positive;
ALTER TABLE document_index_generations
    DROP CONSTRAINT IF EXISTS document_index_generations_vector_dimension_positive;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'document_index_generations'::regclass
          AND conname = 'document_index_generations_expected_count_nonnegative'
    ) THEN
        ALTER TABLE document_index_generations
            ADD CONSTRAINT document_index_generations_expected_count_nonnegative
            CHECK (expected_point_count >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'document_index_generations'::regclass
          AND conname = 'document_index_generations_vector_dimension_nonnegative'
    ) THEN
        ALTER TABLE document_index_generations
            ADD CONSTRAINT document_index_generations_vector_dimension_nonnegative
            CHECK (vector_dimension >= 0);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS document_index_generations_one_active_per_document_uidx
    ON document_index_generations (document_id)
    WHERE state = 'active';
CREATE INDEX IF NOT EXISTS document_index_generations_retiring_idx
    ON document_index_generations (updated_at, id)
    WHERE state = 'retiring';

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS active_index_generation_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'documents'::regclass
          AND conname = 'documents_active_index_generation_matches_document'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_active_index_generation_matches_document
            FOREIGN KEY (active_index_generation_id, id)
            REFERENCES document_index_generations (id, document_id);
    END IF;
END $$;
"""


def ensure_ingest_publication_schema(conn: Any) -> bool:
    """Apply the additive publication migration once per database."""
    conn.execute(_MIGRATION_TABLE_SQL)
    with conn.transaction():
        reserved = conn.execute(
            _RESERVE_MIGRATION_SQL, (INGEST_PUBLICATION_SCHEMA_VERSION,)
        ).fetchone()
        if reserved is None:
            return False
        conn.execute(INGEST_PUBLICATION_SCHEMA_SQL)
    return True


__all__ = [
    "INGEST_PUBLICATION_SCHEMA_SQL",
    "INGEST_PUBLICATION_SCHEMA_VERSION",
    "ensure_ingest_publication_schema",
]
