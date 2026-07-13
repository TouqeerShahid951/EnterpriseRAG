"""PostgreSQL schema for document image assets."""

DOCUMENT_IMAGE_ASSET_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS document_image_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    job_id UUID NULL REFERENCES ingest_jobs(id) ON DELETE SET NULL,
    source_kind TEXT NOT NULL DEFAULT 'image',
    page INTEGER NULL,
    bbox JSONB NULL,
    object_path TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'image/jpeg',
    width INTEGER NULL,
    height INTEGER NULL,
    content_hash TEXT NOT NULL,
    extracted_text TEXT NULL,
    caption TEXT NULL,
    confidence DOUBLE PRECISION NULL,
    quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT document_image_assets_object_path_not_blank CHECK (length(btrim(object_path)) > 0),
    CONSTRAINT document_image_assets_content_hash_not_blank CHECK (length(btrim(content_hash)) > 0),
    CONSTRAINT document_image_assets_quality_flags_array CHECK (jsonb_typeof(quality_flags) = 'array'),
    CONSTRAINT document_image_assets_bbox_array CHECK (bbox IS NULL OR jsonb_typeof(bbox) = 'array'),
    CONSTRAINT document_image_assets_page_positive CHECK (page IS NULL OR page >= 1),
    CONSTRAINT document_image_assets_dimensions_positive CHECK (
        (width IS NULL OR width > 0) AND (height IS NULL OR height > 0)
    )
);

CREATE INDEX IF NOT EXISTS document_image_assets_doc_idx ON document_image_assets (doc_id, created_at);
CREATE INDEX IF NOT EXISTS document_image_assets_job_idx ON document_image_assets (job_id) WHERE job_id IS NOT NULL;
"""
