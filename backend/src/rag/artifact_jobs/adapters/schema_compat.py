"""Compatibility DDL for generated artifact persistence."""

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
