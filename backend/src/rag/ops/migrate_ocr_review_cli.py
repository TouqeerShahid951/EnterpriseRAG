"""Idempotent local schema repair for OCR review support."""

from __future__ import annotations

from rag.core.config import settings
from rag.repositories.postgres import PostgresConnectionMixin


DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS document_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    start_offset INTEGER NULL,
    end_offset INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT document_entities_text_not_blank CHECK (length(btrim(text)) > 0),
    CONSTRAINT document_entities_type_not_blank CHECK (length(btrim(entity_type)) > 0),
    CONSTRAINT document_entities_offsets_valid CHECK (
        start_offset IS NULL OR end_offset IS NULL OR end_offset >= start_offset
    )
);

CREATE INDEX IF NOT EXISTS document_entities_doc_id_idx ON document_entities (doc_id);
CREATE INDEX IF NOT EXISTS document_entities_lookup_idx ON document_entities (lower(text), entity_type);

CREATE TABLE IF NOT EXISTS document_cross_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ref_text TEXT NOT NULL,
    ref_type TEXT NOT NULL,
    position INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT document_cross_references_text_not_blank CHECK (length(btrim(ref_text)) > 0),
    CONSTRAINT document_cross_references_type_not_blank CHECK (length(btrim(ref_type)) > 0)
);

CREATE INDEX IF NOT EXISTS document_cross_references_doc_id_idx ON document_cross_references (doc_id);
CREATE INDEX IF NOT EXISTS document_cross_references_lookup_idx ON document_cross_references (lower(ref_text), ref_type);

CREATE TABLE IF NOT EXISTS human_review_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL,
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parsed_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    resume_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT human_review_batches_status_known CHECK (
        status IN ('pending', 'approved', 'rejected')
    ),
    CONSTRAINT human_review_batches_parsed_items_array CHECK (
        jsonb_typeof(parsed_items) = 'array'
    ),
    CONSTRAINT human_review_batches_resume_payload_object CHECK (
        jsonb_typeof(resume_payload) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS human_review_batches_doc_id_idx ON human_review_batches (doc_id);
CREATE INDEX IF NOT EXISTS human_review_batches_job_id_idx ON human_review_batches (job_id);
CREATE INDEX IF NOT EXISTS human_review_batches_status_idx ON human_review_batches (status, created_at);

CREATE TABLE IF NOT EXISTS human_review_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NULL REFERENCES human_review_batches(id) ON DELETE CASCADE,
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    item_index INTEGER NOT NULL DEFAULT 0,
    item_type TEXT NOT NULL DEFAULT 'text',
    page_start INTEGER NULL,
    page_end INTEGER NULL,
    bbox JSONB NULL,
    quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    partial_text TEXT NULL,
    corrected_text TEXT NULL,
    confidence DOUBLE PRECISION NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_to UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS batch_id UUID NULL REFERENCES human_review_batches(id) ON DELETE CASCADE;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS doc_id UUID;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS item_index INTEGER NOT NULL DEFAULT 0;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS item_type TEXT NOT NULL DEFAULT 'text';
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS page_start INTEGER NULL;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS page_end INTEGER NULL;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS bbox JSONB NULL;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS partial_text TEXT NULL;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS corrected_text TEXT NULL;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NULL;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS assigned_to UUID NULL REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE human_review_queue ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS human_review_queue_status_idx ON human_review_queue (status, created_at);
CREATE INDEX IF NOT EXISTS human_review_queue_doc_id_idx ON human_review_queue (doc_id);
CREATE INDEX IF NOT EXISTS human_review_queue_batch_idx ON human_review_queue (batch_id, item_index);
"""


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        for statement in DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
    print("OCR review schema migration complete.")


if __name__ == "__main__":
    main()
