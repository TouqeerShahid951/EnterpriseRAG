"""Idempotent PostgreSQL schema bootstrap for local deployments."""

from __future__ import annotations

from rag.artifact_jobs.adapters.generated_postgres import GENERATED_ARTIFACT_SCHEMA_SQL
from rag.artifact_jobs.adapters.job_postgres import ARTIFACT_JOB_SCHEMA_SQL
from rag.core.config import Settings, settings
from rag.evaluations.repository import EVALUATION_SCHEMA_SQL
from rag.ops.migrate_folder_ingest_cli import MIGRATION_SQL as FOLDER_INGEST_MIGRATION_SQL
from rag.ops.migrate_ingest_job_origin_cli import MIGRATION_SQL as INGEST_JOB_ORIGIN_MIGRATION_SQL
from rag.ops.migrate_ingest_progress_cli import DDL as INGEST_PROGRESS_DDL
from rag.ops.migrate_ingest_resilience_cli import DDL as INGEST_RESILIENCE_DDL
from rag.ops.migrate_image_review_cli import DDL as IMAGE_REVIEW_DDL
from rag.ops.migrate_ocr_review_cli import DDL as OCR_REVIEW_DDL
from rag.ops.migrate_parser_provenance_cli import DDL as PARSER_PROVENANCE_DDL
from rag.ops.migrate_user_deletion_cli import MIGRATION_SQL as USER_DELETION_MIGRATION_SQL
from rag.query.adapters.chat_history_postgres import CHAT_HISTORY_SCHEMA_SQL
from rag.query.adapters.rag_config_postgres import PostgresRagConfigRepository
from rag.query.adapters.vllm_config_postgres import PostgresVllmDeploymentConfigRepository
from rag.ingestion.adapters.configuration_postgres import PostgresIngestConfigRepository
from rag.shared.persistence import PostgresConnectionMixin


class _SchemaBootstrap(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def ensure_postgres_schema(config: Settings = settings) -> None:
    """Create or repair the application schema before repositories are used."""
    if config.identity_repository == "memory" and config.document_repository == "memory":
        return

    bootstrap = _SchemaBootstrap(config.database_url)
    with bootstrap._connect() as conn:
        conn.execute(BASE_SCHEMA_SQL)

    # This table is referenced by later ingestion-resilience migration SQL.
    PostgresRagConfigRepository(config.database_url).get_active()

    with bootstrap._connect() as conn:
        conn.execute(FOLDER_INGEST_MIGRATION_SQL)
        conn.execute(INGEST_JOB_ORIGIN_MIGRATION_SQL)
        conn.execute(INGEST_PROGRESS_DDL)
        conn.execute(PARSER_PROVENANCE_DDL)
        conn.execute(INGEST_RESILIENCE_DDL)
        conn.execute(OCR_REVIEW_DDL)
        conn.execute(IMAGE_REVIEW_DDL)
        conn.execute(USER_DELETION_MIGRATION_SQL)
        conn.execute(CLAIM_SCHEMA_SQL)
        conn.execute(DOCUMENT_IMAGE_ASSET_SCHEMA_SQL)
        conn.execute(CHAT_HISTORY_SCHEMA_SQL)
        conn.execute(ARTIFACT_JOB_SCHEMA_SQL)
        conn.execute(GENERATED_ARTIFACT_SCHEMA_SQL)
        conn.execute(GENERATED_ARTIFACT_COMPAT_SQL)
        conn.execute(EVALUATION_SCHEMA_SQL)
        conn.execute(CONNECTOR_SCHEMA_SQL)
        conn.execute(DEFAULT_GROUP_CLEANUP_SQL)

    # Reuse repository-owned schema repair for workspace configuration tables.
    PostgresIngestConfigRepository(config.database_url).get_active()
    PostgresVllmDeploymentConfigRepository(config.database_url).get_active()


BASE_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS groups (
    path TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT groups_path_format CHECK (path ~ '^/[a-z0-9][a-z0-9-]*$'),
    CONSTRAINT groups_name_not_blank CHECK (length(btrim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    account_type TEXT NOT NULL DEFAULT 'member',
    clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED',
    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
    permission_version INTEGER NOT NULL DEFAULT 1,
    last_login_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_email_not_blank CHECK (length(btrim(email)) > 0),
    CONSTRAINT users_name_not_blank CHECK (length(btrim(name)) > 0),
    CONSTRAINT users_account_type_known CHECK (
        account_type IN (
            'platform_admin', 'system_admin', 'user_manager', 'space_admin',
            'contributor', 'reviewer', 'auditor', 'member'
        )
    ),
    CONSTRAINT users_clearance_level_known CHECK (
        clearance_level IN (
            'NATO_UNCLASSIFIED', 'NATO_RESTRICTED', 'NATO_CONFIDENTIAL',
            'NATO_SECRET', 'COSMIC_TOP_SECRET'
        )
    ),
    CONSTRAINT users_permission_version_positive CHECK (permission_version >= 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS users_email_uidx ON users (lower(email));

CREATE TABLE IF NOT EXISTS user_groups (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_path TEXT NOT NULL REFERENCES groups(path) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, group_path)
);

CREATE INDEX IF NOT EXISTS user_groups_group_path_idx ON user_groups (group_path);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NULL,
    source_id TEXT NOT NULL,
    group_path TEXT NOT NULL REFERENCES groups(path) ON UPDATE CASCADE ON DELETE RESTRICT,
    clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED',
    doc_type TEXT NULL,
    language TEXT NULL,
    effective_date DATE NULL,
    expiry_date DATE NULL,
    description TEXT NULL,
    summary TEXT NULL,
    topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    llm_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    auto_doc_type TEXT NULL,
    extracted_dates JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    superseded_by UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
    pending_supersedes JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash TEXT NULL,
    uploaded_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    file_path TEXT NULL,
    ingest_status TEXT NOT NULL DEFAULT 'queued',
    deleted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT documents_source_id_not_blank CHECK (length(btrim(source_id)) > 0),
    CONSTRAINT documents_topics_array CHECK (jsonb_typeof(topics) = 'array'),
    CONSTRAINT documents_llm_topics_array CHECK (jsonb_typeof(llm_topics) = 'array'),
    CONSTRAINT documents_extracted_dates_object CHECK (jsonb_typeof(extracted_dates) = 'object'),
    CONSTRAINT documents_metadata_flags_object CHECK (jsonb_typeof(metadata_flags) = 'object'),
    CONSTRAINT documents_pending_supersedes_array CHECK (jsonb_typeof(pending_supersedes) = 'array'),
    CONSTRAINT documents_expiry_after_effective CHECK (expiry_date IS NULL OR effective_date IS NULL OR expiry_date >= effective_date),
    CONSTRAINT documents_clearance_level_known CHECK (
        clearance_level IN (
            'NATO_UNCLASSIFIED', 'NATO_RESTRICTED', 'NATO_CONFIDENTIAL',
            'NATO_SECRET', 'COSMIC_TOP_SECRET'
        )
    ),
    CONSTRAINT documents_ingest_status_known CHECK (
        ingest_status IN ('scheduled', 'queued', 'processing', 'complete', 'failed', 'human_review', 'cancelled')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS documents_source_id_uidx ON documents (source_id);
CREATE INDEX IF NOT EXISTS documents_group_path_idx ON documents (group_path);
CREATE INDEX IF NOT EXISTS documents_clearance_level_idx ON documents (clearance_level);
CREATE INDEX IF NOT EXISTS documents_current_idx ON documents (is_current, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS documents_content_hash_current_idx ON documents (content_hash) WHERE deleted_at IS NULL AND is_current = TRUE;

CREATE TABLE IF NOT EXISTS document_shares (
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    group_path TEXT NOT NULL REFERENCES groups(path) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (document_id, group_path)
);

CREATE INDEX IF NOT EXISTS document_shares_group_path_idx ON document_shares (group_path);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    retry_of_job_id UUID NULL REFERENCES ingest_jobs(id) ON DELETE SET NULL,
    origin TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'queued',
    progress_pct INTEGER NOT NULL DEFAULT 0,
    stage_progress JSONB NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_at TIMESTAMPTZ NULL,
    run_token TEXT NULL,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    parser_provenance JSONB NULL,
    error_code TEXT NULL,
    error_message_safe TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL,
    CONSTRAINT ingest_jobs_origin_known CHECK (
        origin IN ('upload', 'reingest', 'restore', 'folder', 'connector', 'unknown')
    ),
    CONSTRAINT ingest_jobs_status_known CHECK (
        status IN ('scheduled', 'queued', 'processing', 'complete', 'failed', 'human_review', 'cancelled')
    ),
    CONSTRAINT ingest_jobs_progress_valid CHECK (progress_pct BETWEEN 0 AND 100),
    CONSTRAINT ingest_jobs_attempt_count_nonnegative CHECK (attempt_count >= 0),
    CONSTRAINT ingest_jobs_warnings_array CHECK (jsonb_typeof(warnings) = 'array'),
    CONSTRAINT ingest_jobs_stage_progress_object CHECK (
        stage_progress IS NULL OR jsonb_typeof(stage_progress) = 'object'
    ),
    CONSTRAINT ingest_jobs_parser_provenance_object CHECK (
        parser_provenance IS NULL OR jsonb_typeof(parser_provenance) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS ingest_jobs_doc_created_idx ON ingest_jobs (doc_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ingest_jobs_retry_of_idx ON ingest_jobs (retry_of_job_id);
CREATE UNIQUE INDEX IF NOT EXISTS ingest_jobs_one_active_per_doc_uidx
    ON ingest_jobs (doc_id)
    WHERE status IN ('scheduled', 'queued', 'processing', 'human_review');

CREATE TABLE IF NOT EXISTS supersession_edges (
    old_doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    new_doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (old_doc_id, new_doc_id),
    CONSTRAINT supersession_edges_not_self CHECK (old_doc_id <> new_doc_id)
);

CREATE INDEX IF NOT EXISTS supersession_edges_new_doc_idx ON supersession_edges (new_doc_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    actor_id UUID NULL,
    target_type TEXT NULL,
    target_id TEXT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT audit_log_event_type_not_blank CHECK (length(btrim(event_type)) > 0),
    CONSTRAINT audit_log_payload_object CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS audit_log_created_idx ON audit_log (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS audit_log_actor_idx ON audit_log (actor_id) WHERE actor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS audit_log_target_idx ON audit_log (target_type, target_id) WHERE target_type IS NOT NULL;
"""


DEFAULT_GROUP_CLEANUP_SQL = """
DELETE FROM groups AS group_row
WHERE group_row.path IN ('/admin', '/review', '/finance', '/engineering')
  AND NOT EXISTS (
    SELECT 1 FROM user_groups AS user_group
    WHERE user_group.group_path = group_row.path
  )
  AND NOT EXISTS (
    SELECT 1 FROM documents AS document
    WHERE document.group_path = group_row.path
  )
  AND NOT EXISTS (
    SELECT 1 FROM document_shares AS share
    WHERE share.group_path = group_row.path
  )
  AND NOT EXISTS (
    SELECT 1 FROM folder_ingest_schedules AS schedule
    WHERE schedule.group_path = group_row.path
  )
  AND NOT EXISTS (
    SELECT 1 FROM connector_schema_catalogs AS catalog
    WHERE catalog.group_path = group_row.path
  )
  AND NOT EXISTS (
    SELECT 1 FROM artifact_generation_jobs AS artifact_job
    WHERE artifact_job.group_path = group_row.path
  )
  AND NOT EXISTS (
    SELECT 1 FROM rag_evaluation_runs AS evaluation_run
    WHERE evaluation_run.group_path = group_row.path
  );
"""


CONNECTOR_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS connector_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    connector_type TEXT NOT NULL,
    public_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    encrypted_secrets TEXT NOT NULL,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    last_test_status TEXT NULL,
    last_test_message TEXT NULL,
    last_tested_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT connector_profiles_name_not_blank CHECK (length(btrim(name)) > 0),
    CONSTRAINT connector_profiles_config_object CHECK (jsonb_typeof(public_config) = 'object'),
    CONSTRAINT connector_profiles_type_known CHECK (
        connector_type IN (
            'sql_server', 'postgres', 'mysql', 'mariadb', 'mongodb', 'oracle',
            'opensearch', 'elasticsearch', 'redis', 'cassandra', 'fake'
        )
    ),
    CONSTRAINT connector_profiles_test_status_known CHECK (
        last_test_status IS NULL OR last_test_status IN ('ok', 'failed')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS connector_profiles_name_uidx ON connector_profiles (lower(name));

CREATE TABLE IF NOT EXISTS connector_schema_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES connector_profiles(id) ON DELETE CASCADE,
    connector_type TEXT NOT NULL,
    schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'ok',
    error_message_safe TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT connector_schema_snapshots_json_object CHECK (jsonb_typeof(schema_json) = 'object'),
    CONSTRAINT connector_schema_snapshots_status_known CHECK (status IN ('ok', 'failed'))
);

CREATE INDEX IF NOT EXISTS connector_schema_snapshots_profile_idx
    ON connector_schema_snapshots (profile_id, created_at DESC);

CREATE TABLE IF NOT EXISTS connector_schema_catalogs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES connector_profiles(id) ON DELETE CASCADE,
    connector_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    group_path TEXT NOT NULL REFERENCES groups(path) ON UPDATE CASCADE ON DELETE RESTRICT,
    clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED',
    catalog_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    approved_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT connector_schema_catalogs_json_object CHECK (jsonb_typeof(catalog_json) = 'object'),
    CONSTRAINT connector_schema_catalogs_status_known CHECK (
        status IN ('draft', 'reviewed', 'approved', 'disabled')
    ),
    CONSTRAINT connector_schema_catalogs_clearance_level_known CHECK (
        clearance_level IN (
            'NATO_UNCLASSIFIED', 'NATO_RESTRICTED', 'NATO_CONFIDENTIAL',
            'NATO_SECRET', 'COSMIC_TOP_SECRET'
        )
    )
);

CREATE INDEX IF NOT EXISTS connector_schema_catalogs_profile_idx
    ON connector_schema_catalogs (profile_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS connector_schema_catalogs_access_idx
    ON connector_schema_catalogs (group_path, clearance_level, status);

ALTER TABLE folder_ingest_schedules DROP CONSTRAINT IF EXISTS folder_ingest_schedules_source_type_known;
ALTER TABLE folder_ingest_schedules ADD CONSTRAINT folder_ingest_schedules_source_type_known CHECK (
    source_type IN ('snapshot', 'local_folder', 'minio_prefix')
) NOT VALID;

ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_origin_known;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_origin_known CHECK (
    origin IN ('upload', 'reingest', 'restore', 'folder', 'connector', 'unknown')
);
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS retry_of_job_id UUID NULL REFERENCES ingest_jobs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ingest_jobs_retry_of_idx ON ingest_jobs (retry_of_job_id);
"""


CLAIM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL,
    entity TEXT NOT NULL,
    attribute TEXT NOT NULL,
    value TEXT NOT NULL,
    entity_norm TEXT GENERATED ALWAYS AS (lower(btrim(entity))) STORED,
    attribute_norm TEXT GENERATED ALWAYS AS (lower(btrim(attribute))) STORED,
    value_norm TEXT GENERATED ALWAYS AS (lower(btrim(value))) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT claims_chunk_id_not_blank CHECK (length(btrim(chunk_id)) > 0),
    CONSTRAINT claims_entity_not_blank CHECK (length(btrim(entity)) > 0),
    CONSTRAINT claims_attribute_not_blank CHECK (length(btrim(attribute)) > 0),
    CONSTRAINT claims_value_not_blank CHECK (length(btrim(value)) > 0)
);

CREATE INDEX IF NOT EXISTS claims_doc_idx ON claims (doc_id, created_at);
CREATE INDEX IF NOT EXISTS claims_lookup_idx ON claims (entity_norm, attribute_norm);

CREATE TABLE IF NOT EXISTS conflicts (
    claim_a_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    claim_b_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (claim_a_id, claim_b_id),
    CONSTRAINT conflicts_status_known CHECK (status IN ('open', 'resolved')),
    CONSTRAINT conflicts_not_self CHECK (claim_a_id <> claim_b_id)
);

CREATE INDEX IF NOT EXISTS conflicts_status_idx ON conflicts (status, created_at);
"""


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


GENERATED_ARTIFACT_COMPAT_SQL = """
ALTER TABLE generated_artifacts ADD COLUMN IF NOT EXISTS job_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'generated_artifacts_job_id_fkey'
    ) THEN
        ALTER TABLE generated_artifacts
        ADD CONSTRAINT generated_artifacts_job_id_fkey
        FOREIGN KEY (job_id)
        REFERENCES artifact_generation_jobs(id)
        ON DELETE CASCADE;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS generated_artifacts_job_format_uidx
    ON generated_artifacts (job_id, artifact_format)
    WHERE job_id IS NOT NULL;
"""
