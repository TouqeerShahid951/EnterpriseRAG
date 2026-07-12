"""PostgreSQL generated artifact repository."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from ...shared.persistence import PostgresConnectionMixin
from ..generated_models import GeneratedArtifactRecord
from .job_postgres import ARTIFACT_JOB_SCHEMA_SQL


class PostgresGeneratedArtifactRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str, default_retention_days: int = 30) -> None:
        if default_retention_days < 1:
            raise ValueError("default_retention_days must be positive")
        self.database_url = database_url
        self.default_retention_days = default_retention_days
        self._ensure_tables()

    def create_artifact(
        self,
        *,
        user_id: str,
        permission_version: int,
        session_id: str,
        trace_id: str,
        requested_formats: list[str],
        filename: str,
        format: str,
        content_type: str,
        object_path: str,
        size_bytes: int,
        source_doc_ids: list[str],
        prompt: str,
        job_id: str | None = None,
        expires_at: datetime | None = None,
        expected_job_run_token: str | None = None,
    ) -> GeneratedArtifactRecord:
        if expires_at is not None:
            _validate_timestamp(expires_at, field_name="expires_at")
        if expected_job_run_token is not None:
            if job_id is None:
                raise ValueError("expected_job_run_token requires job_id")
            return self._create_guarded_artifact(
                user_id=user_id,
                permission_version=permission_version,
                session_id=session_id,
                trace_id=trace_id,
                requested_formats=requested_formats,
                filename=filename,
                format=format,
                content_type=content_type,
                object_path=object_path,
                size_bytes=size_bytes,
                source_doc_ids=source_doc_ids,
                prompt=prompt,
                job_id=job_id,
                expires_at=expires_at,
                expected_job_run_token=expected_job_run_token,
            )
        conflict_target = (
            "(job_id, artifact_format) WHERE job_id IS NOT NULL"
            if job_id is not None
            else "(user_id, permission_version, trace_id, artifact_format) WHERE job_id IS NULL"
        )
        row = self._execute_one(
            f"""
            INSERT INTO generated_artifacts (
                job_id, user_id, permission_version, session_id, trace_id, requested_formats,
                filename, artifact_format, content_type, object_path, size_bytes,
                source_doc_ids, prompt, expires_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s,
                COALESCE(
                    %s,
                    (SELECT expires_at FROM artifact_generation_jobs WHERE id = %s),
                    NOW() + (%s * INTERVAL '1 day')
                )
            )
            ON CONFLICT {conflict_target}
            DO UPDATE SET
                filename = EXCLUDED.filename,
                content_type = EXCLUDED.content_type,
                object_path = EXCLUDED.object_path,
                size_bytes = EXCLUDED.size_bytes,
                source_doc_ids = EXCLUDED.source_doc_ids,
                prompt = EXCLUDED.prompt,
                expires_at = EXCLUDED.expires_at
            RETURNING *
            """,
            (
                job_id,
                user_id,
                permission_version,
                session_id,
                trace_id,
                json.dumps(requested_formats),
                filename,
                format,
                content_type,
                object_path,
                size_bytes,
                json.dumps(source_doc_ids),
                prompt,
                expires_at,
                job_id,
                self.default_retention_days,
            ),
        )
        return artifact_from_row(row)

    def _create_guarded_artifact(
        self,
        *,
        user_id: str,
        permission_version: int,
        session_id: str,
        trace_id: str,
        requested_formats: list[str],
        filename: str,
        format: str,
        content_type: str,
        object_path: str,
        size_bytes: int,
        source_doc_ids: list[str],
        prompt: str,
        job_id: str,
        expires_at: datetime | None,
        expected_job_run_token: str,
    ) -> GeneratedArtifactRecord:
        row = self._execute_optional(
            """
            WITH authorized_job AS (
                SELECT id, expires_at
                FROM artifact_generation_jobs
                WHERE id = %s
                  AND run_token = %s
                  AND status IN (
                      'planning', 'retrieving', 'composing', 'validating', 'rendering'
                  )
                  AND expires_at > NOW()
                FOR UPDATE
            )
            INSERT INTO generated_artifacts (
                job_id, user_id, permission_version, session_id, trace_id, requested_formats,
                filename, artifact_format, content_type, object_path, size_bytes,
                source_doc_ids, prompt, expires_at
            )
            SELECT
                job.id, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s,
                COALESCE(%s, job.expires_at, NOW() + (%s * INTERVAL '1 day'))
            FROM authorized_job AS job
            ON CONFLICT (job_id, artifact_format) WHERE job_id IS NOT NULL
            DO UPDATE SET
                filename = EXCLUDED.filename,
                content_type = EXCLUDED.content_type,
                object_path = EXCLUDED.object_path,
                size_bytes = EXCLUDED.size_bytes,
                source_doc_ids = EXCLUDED.source_doc_ids,
                prompt = EXCLUDED.prompt,
                expires_at = EXCLUDED.expires_at
            WHERE EXISTS (SELECT 1 FROM authorized_job)
            RETURNING *
            """,
            (
                job_id,
                expected_job_run_token,
                user_id,
                permission_version,
                session_id,
                trace_id,
                json.dumps(requested_formats),
                filename,
                format,
                content_type,
                object_path,
                size_bytes,
                json.dumps(source_doc_ids),
                prompt,
                expires_at,
                self.default_retention_days,
            ),
        )
        if row is None:
            raise RuntimeError("artifact publication lease is no longer valid")
        return artifact_from_row(row)

    def get_artifact(self, artifact_id: str) -> GeneratedArtifactRecord | None:
        row = self._execute_optional(
            "SELECT * FROM generated_artifacts WHERE id = %s", (artifact_id,)
        )
        return artifact_from_row(row) if row else None

    def list_artifacts_for_job(self, job_id: str) -> list[GeneratedArtifactRecord]:
        rows = self._execute_all(
            "SELECT * FROM generated_artifacts WHERE job_id = %s ORDER BY created_at, artifact_format",
            (job_id,),
        )
        return [artifact_from_row(row) for row in rows]

    def delete_artifact(
        self,
        artifact_id: str,
        *,
        expected_object_path: str,
    ) -> bool:
        row = self._execute_optional(
            """
            DELETE FROM generated_artifacts
            WHERE id = %s AND object_path = %s
            RETURNING id
            """,
            (artifact_id, expected_object_path),
        )
        return row is not None

    def is_object_path_referenced(
        self,
        object_path: str,
        *,
        excluding_artifact_id: str | None = None,
    ) -> bool:
        row = self._execute_optional(
            """
            SELECT id
            FROM generated_artifacts
            WHERE object_path = %s
              AND (%s IS NULL OR id <> %s)
            LIMIT 1
            """,
            (object_path, excluding_artifact_id, excluding_artifact_id),
        )
        return row is not None

    def list_expired_artifacts(
        self,
        *,
        expires_before: datetime,
        limit: int = 100,
    ) -> list[GeneratedArtifactRecord]:
        _validate_timestamp(expires_before, field_name="expires_before")
        _validate_limit(limit)
        rows = self._execute_all(
            """
            SELECT * FROM generated_artifacts
            WHERE expires_at <= %s
            ORDER BY expires_at, id
            LIMIT %s
            """,
            (expires_before, limit),
        )
        return [artifact_from_row(row) for row in rows]

    def delete_expired_artifact(
        self,
        artifact_id: str,
        *,
        expires_before: datetime,
        expected_object_path: str,
    ) -> bool:
        _validate_timestamp(expires_before, field_name="expires_before")
        row = self._execute_optional(
            """
            DELETE FROM generated_artifacts
            WHERE id = %s AND expires_at <= %s AND object_path = %s
            RETURNING id
            """,
            (artifact_id, expires_before, expected_object_path),
        )
        return row is not None

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(ARTIFACT_JOB_SCHEMA_SQL)
            conn.execute(_GENERATED_ARTIFACT_TABLE_SCHEMA_SQL)
            conn.execute(
                "ALTER TABLE generated_artifacts ADD COLUMN IF NOT EXISTS job_id UUID NULL"
            )
            conn.execute(
                "ALTER TABLE generated_artifacts ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL"
            )
            conn.execute(
                """
                UPDATE generated_artifacts AS artifact
                SET expires_at = COALESCE(
                    (
                        SELECT job.expires_at
                        FROM artifact_generation_jobs AS job
                        WHERE job.id = artifact.job_id
                    ),
                    artifact.created_at + (%s * INTERVAL '1 day')
                )
                WHERE artifact.expires_at IS NULL
                """,
                (self.default_retention_days,),
            )
            conn.execute(
                "ALTER TABLE generated_artifacts ALTER COLUMN expires_at SET NOT NULL"
            )
            conn.execute(
                """
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
                """
            )
            conn.execute(_GENERATED_ARTIFACT_INDEX_SCHEMA_SQL)
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS generated_artifacts_job_format_uidx
                ON generated_artifacts (job_id, artifact_format)
                WHERE job_id IS NOT NULL
                """
            )


def artifact_from_row(row: dict[str, Any]) -> GeneratedArtifactRecord:
    requested_formats = _json_list(row.get("requested_formats"))
    source_doc_ids = _json_list(row.get("source_doc_ids"))
    return GeneratedArtifactRecord(
        id=str(row["id"]),
        job_id=str(row["job_id"]) if row.get("job_id") else None,
        user_id=str(row["user_id"]),
        permission_version=int(row["permission_version"]),
        session_id=str(row["session_id"]),
        trace_id=str(row["trace_id"]),
        requested_formats=tuple(requested_formats),
        filename=str(row["filename"]),
        format=str(row["artifact_format"]),
        content_type=str(row["content_type"]),
        object_path=str(row["object_path"]),
        size_bytes=int(row["size_bytes"]),
        source_doc_ids=tuple(source_doc_ids),
        prompt=str(row["prompt"]),
        created_at=row.get("created_at"),
        expires_at=row.get("expires_at"),
    )


def _json_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _validate_timestamp(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _validate_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be positive")


_GENERATED_ARTIFACT_TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generated_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NULL REFERENCES artifact_generation_jobs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission_version INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    requested_formats JSONB NOT NULL DEFAULT '[]'::jsonb,
    filename TEXT NOT NULL,
    artifact_format TEXT NOT NULL,
    content_type TEXT NOT NULL,
    object_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    source_doc_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT generated_artifacts_session_not_blank CHECK (length(btrim(session_id)) > 0),
    CONSTRAINT generated_artifacts_trace_not_blank CHECK (length(btrim(trace_id)) > 0),
    CONSTRAINT generated_artifacts_filename_not_blank CHECK (length(btrim(filename)) > 0),
    CONSTRAINT generated_artifacts_format_known CHECK (artifact_format IN ('docx', 'pptx', 'pdf')),
    CONSTRAINT generated_artifacts_content_type_not_blank CHECK (length(btrim(content_type)) > 0),
    CONSTRAINT generated_artifacts_object_path_not_blank CHECK (length(btrim(object_path)) > 0),
    CONSTRAINT generated_artifacts_size_nonnegative CHECK (size_bytes >= 0),
    CONSTRAINT generated_artifacts_requested_formats_array CHECK (jsonb_typeof(requested_formats) = 'array'),
    CONSTRAINT generated_artifacts_source_doc_ids_array CHECK (jsonb_typeof(source_doc_ids) = 'array')
);
"""

_GENERATED_ARTIFACT_EXPIRY_COMPAT_SQL = """
ALTER TABLE generated_artifacts
    ADD COLUMN IF NOT EXISTS job_id UUID NULL;

ALTER TABLE generated_artifacts
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL;

UPDATE generated_artifacts AS artifact
SET expires_at = COALESCE(
    (
        SELECT job.expires_at
        FROM artifact_generation_jobs AS job
        WHERE job.id = artifact.job_id
    ),
    artifact.created_at + INTERVAL '30 days'
)
WHERE artifact.expires_at IS NULL;

ALTER TABLE generated_artifacts
    ALTER COLUMN expires_at SET NOT NULL;
"""

_GENERATED_ARTIFACT_INDEX_SCHEMA_SQL = """
CREATE INDEX IF NOT EXISTS generated_artifacts_user_created_idx
    ON generated_artifacts (user_id, permission_version, created_at DESC);

CREATE INDEX IF NOT EXISTS generated_artifacts_session_idx
    ON generated_artifacts (session_id, user_id, permission_version);

CREATE INDEX IF NOT EXISTS generated_artifacts_expiry_idx
    ON generated_artifacts (expires_at, id);

CREATE UNIQUE INDEX IF NOT EXISTS generated_artifacts_job_format_uidx
    ON generated_artifacts (job_id, artifact_format)
    WHERE job_id IS NOT NULL;

DELETE FROM generated_artifacts AS older
USING generated_artifacts AS newer
WHERE older.job_id IS NULL
  AND newer.job_id IS NULL
  AND older.user_id = newer.user_id
  AND older.permission_version = newer.permission_version
  AND older.trace_id = newer.trace_id
  AND older.artifact_format = newer.artifact_format
  AND (older.created_at, older.id) < (newer.created_at, newer.id);

CREATE UNIQUE INDEX IF NOT EXISTS generated_artifacts_trace_format_uidx
    ON generated_artifacts (user_id, permission_version, trace_id, artifact_format)
    WHERE job_id IS NULL;
"""

GENERATED_ARTIFACT_SCHEMA_SQL = (
    _GENERATED_ARTIFACT_TABLE_SCHEMA_SQL
    + _GENERATED_ARTIFACT_EXPIRY_COMPAT_SQL
    + _GENERATED_ARTIFACT_INDEX_SCHEMA_SQL
)
