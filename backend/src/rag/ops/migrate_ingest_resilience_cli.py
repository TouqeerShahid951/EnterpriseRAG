"""Idempotent schema migration for resilient ingestion execution."""

from __future__ import annotations

from rag.core.config import settings
from rag.shared.persistence import PostgresConnectionMixin


DDL = """
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ NULL;
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS run_token TEXT NULL;
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS warnings JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_attempt_count_nonnegative;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_attempt_count_nonnegative CHECK (attempt_count >= 0);
ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_warnings_array;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_warnings_array CHECK (jsonb_typeof(warnings) = 'array');

CREATE TABLE IF NOT EXISTS workspace_ingest_config (
    config_key TEXT PRIMARY KEY DEFAULT 'active',
    worker_concurrency INTEGER NOT NULL DEFAULT 1,
    quality_preset TEXT NOT NULL DEFAULT 'fast',
    ocr_review_confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.9,
    pdf_image_review_threshold INTEGER NOT NULL DEFAULT 64,
    vision_layout_repair_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    graph_enrichment_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT workspace_ingest_config_singleton CHECK (config_key = 'active'),
    CONSTRAINT workspace_ingest_config_concurrency_range CHECK (worker_concurrency BETWEEN 1 AND 10),
    CONSTRAINT workspace_ingest_config_quality_preset CHECK (
        quality_preset IN ('fast', 'balanced', 'high_accuracy')
    ),
    CONSTRAINT workspace_ingest_config_ocr_review_threshold CHECK (
        ocr_review_confidence_threshold >= 0 AND ocr_review_confidence_threshold <= 1
    ),
    CONSTRAINT workspace_ingest_config_pdf_image_review_threshold CHECK (
        pdf_image_review_threshold BETWEEN 0 AND 10000
    )
);
INSERT INTO workspace_ingest_config (config_key, worker_concurrency)
VALUES ('active', 1)
ON CONFLICT (config_key) DO NOTHING;
ALTER TABLE workspace_ingest_config
    ADD COLUMN IF NOT EXISTS quality_preset TEXT NOT NULL DEFAULT 'fast';
ALTER TABLE workspace_ingest_config
    ADD COLUMN IF NOT EXISTS ocr_review_confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.9;
ALTER TABLE workspace_ingest_config
    ADD COLUMN IF NOT EXISTS pdf_image_review_threshold INTEGER NOT NULL DEFAULT 64;
ALTER TABLE workspace_ingest_config
    ADD COLUMN IF NOT EXISTS vision_layout_repair_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE workspace_ingest_config
    ADD COLUMN IF NOT EXISTS graph_enrichment_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE workspace_ingest_config DROP CONSTRAINT IF EXISTS workspace_ingest_config_quality_preset;
ALTER TABLE workspace_ingest_config ADD CONSTRAINT workspace_ingest_config_quality_preset CHECK (
    quality_preset IN ('fast', 'balanced', 'high_accuracy')
);
ALTER TABLE workspace_ingest_config DROP CONSTRAINT IF EXISTS workspace_ingest_config_ocr_review_threshold;
ALTER TABLE workspace_ingest_config ADD CONSTRAINT workspace_ingest_config_ocr_review_threshold CHECK (
    ocr_review_confidence_threshold >= 0 AND ocr_review_confidence_threshold <= 1
);
ALTER TABLE workspace_ingest_config DROP CONSTRAINT IF EXISTS workspace_ingest_config_pdf_image_review_threshold;
ALTER TABLE workspace_ingest_config ADD CONSTRAINT workspace_ingest_config_pdf_image_review_threshold CHECK (
    pdf_image_review_threshold BETWEEN 0 AND 10000
);

ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS chat_latency_ms DOUBLE PRECISION NULL;
ALTER TABLE workspace_rag_config ADD COLUMN IF NOT EXISTS embed_latency_ms DOUBLE PRECISION NULL;
ALTER TABLE workspace_rag_config DROP CONSTRAINT IF EXISTS workspace_rag_config_latency_nonnegative;
ALTER TABLE workspace_rag_config ADD CONSTRAINT workspace_rag_config_latency_nonnegative CHECK (
    (chat_latency_ms IS NULL OR chat_latency_ms >= 0)
    AND (embed_latency_ms IS NULL OR embed_latency_ms >= 0)
);
"""


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        conn.execute(DDL)
    print("Ingestion resilience schema migration complete.")


if __name__ == "__main__":
    main()
