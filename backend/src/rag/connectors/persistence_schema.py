"""PostgreSQL schema owned by the connectors feature."""

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
