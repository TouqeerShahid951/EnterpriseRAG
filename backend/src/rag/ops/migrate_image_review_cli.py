"""Idempotent local schema repair for PDF image review support."""

from __future__ import annotations

from rag.core.config import settings
from rag.repositories.postgres import PostgresConnectionMixin


DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS image_review_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL,
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parsed_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    resume_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    recommended_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT image_review_batches_status_known CHECK (
        status IN ('pending', 'approved', 'rejected')
    ),
    CONSTRAINT image_review_batches_parsed_items_array CHECK (
        jsonb_typeof(parsed_items) = 'array'
    ),
    CONSTRAINT image_review_batches_resume_payload_object CHECK (
        jsonb_typeof(resume_payload) = 'object'
    ),
    CONSTRAINT image_review_batches_candidate_count_nonnegative CHECK (candidate_count >= 0),
    CONSTRAINT image_review_batches_recommended_count_nonnegative CHECK (recommended_count >= 0)
);

ALTER TABLE image_review_batches ADD COLUMN IF NOT EXISTS parsed_items JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE image_review_batches ADD COLUMN IF NOT EXISTS resume_payload JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE image_review_batches ADD COLUMN IF NOT EXISTS candidate_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE image_review_batches ADD COLUMN IF NOT EXISTS recommended_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS image_review_batches_doc_id_idx ON image_review_batches (doc_id);
CREATE INDEX IF NOT EXISTS image_review_batches_job_id_idx ON image_review_batches (job_id);
CREATE INDEX IF NOT EXISTS image_review_batches_status_idx ON image_review_batches (status, created_at);

CREATE TABLE IF NOT EXISTS image_review_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES image_review_batches(id) ON DELETE CASCADE,
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    candidate_key TEXT NOT NULL,
    filename TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'pdf_image',
    page INTEGER NULL,
    bbox JSONB NULL,
    page_area_ratio DOUBLE PRECISION NULL,
    object_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    width INTEGER NULL,
    height INTEGER NULL,
    content_hash TEXT NOT NULL,
    quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    score INTEGER NOT NULL DEFAULT 0,
    recommended BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_to UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    skip_reason TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT image_review_candidates_status_known CHECK (
        status IN ('pending', 'approved', 'skipped')
    ),
    CONSTRAINT image_review_candidates_candidate_key_not_blank CHECK (length(btrim(candidate_key)) > 0),
    CONSTRAINT image_review_candidates_filename_not_blank CHECK (length(btrim(filename)) > 0),
    CONSTRAINT image_review_candidates_object_path_not_blank CHECK (length(btrim(object_path)) > 0),
    CONSTRAINT image_review_candidates_content_hash_not_blank CHECK (length(btrim(content_hash)) > 0),
    CONSTRAINT image_review_candidates_quality_flags_array CHECK (jsonb_typeof(quality_flags) = 'array'),
    CONSTRAINT image_review_candidates_bbox_array CHECK (bbox IS NULL OR jsonb_typeof(bbox) = 'array'),
    CONSTRAINT image_review_candidates_page_positive CHECK (page IS NULL OR page >= 1),
    CONSTRAINT image_review_candidates_dimensions_positive CHECK (
        (width IS NULL OR width > 0) AND (height IS NULL OR height > 0)
    )
);

ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS candidate_key TEXT;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS filename TEXT NOT NULL DEFAULT 'image';
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'pdf_image';
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS page INTEGER NULL;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS bbox JSONB NULL;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS page_area_ratio DOUBLE PRECISION NULL;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS object_path TEXT;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS content_type TEXT NOT NULL DEFAULT 'image/png';
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS width INTEGER NULL;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS height INTEGER NULL;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS score INTEGER NOT NULL DEFAULT 0;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS recommended BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS assigned_to UUID NULL REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS skip_reason TEXT NULL;
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE image_review_candidates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS image_review_candidates_batch_key_uidx ON image_review_candidates (batch_id, candidate_key);
CREATE INDEX IF NOT EXISTS image_review_candidates_batch_status_idx ON image_review_candidates (batch_id, status);
CREATE INDEX IF NOT EXISTS image_review_candidates_doc_id_idx ON image_review_candidates (doc_id);
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
    print("Image review schema migration complete.")


if __name__ == "__main__":
    main()
