"""Foundational PostgreSQL tables and cross-feature cleanup DDL."""

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
