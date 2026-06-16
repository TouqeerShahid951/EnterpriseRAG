"""PostgreSQL generated artifact repository."""

from __future__ import annotations

import json
from typing import Any

from .generated_artifact_models import GeneratedArtifactRecord
from .artifact_jobs import ARTIFACT_JOB_SCHEMA_SQL
from .postgres import PostgresConnectionMixin


class PostgresGeneratedArtifactRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
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
    ) -> GeneratedArtifactRecord:
        row = self._execute_one(
            """
            INSERT INTO generated_artifacts (
                job_id, user_id, permission_version, session_id, trace_id, requested_formats,
                filename, artifact_format, content_type, object_path, size_bytes,
                source_doc_ids, prompt
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (job_id, artifact_format) WHERE job_id IS NOT NULL
            DO UPDATE SET
                filename = EXCLUDED.filename,
                content_type = EXCLUDED.content_type,
                object_path = EXCLUDED.object_path,
                size_bytes = EXCLUDED.size_bytes,
                source_doc_ids = EXCLUDED.source_doc_ids,
                prompt = EXCLUDED.prompt
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
            ),
        )
        return artifact_from_row(row)

    def get_artifact(self, artifact_id: str) -> GeneratedArtifactRecord | None:
        row = self._execute_optional("SELECT * FROM generated_artifacts WHERE id = %s", (artifact_id,))
        return artifact_from_row(row) if row else None

    def list_artifacts_for_job(self, job_id: str) -> list[GeneratedArtifactRecord]:
        rows = self._execute_all(
            "SELECT * FROM generated_artifacts WHERE job_id = %s ORDER BY created_at, artifact_format",
            (job_id,),
        )
        return [artifact_from_row(row) for row in rows]

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(ARTIFACT_JOB_SCHEMA_SQL)
            conn.execute(_GENERATED_ARTIFACT_TABLE_SCHEMA_SQL)
            conn.execute("ALTER TABLE generated_artifacts ADD COLUMN IF NOT EXISTS job_id UUID NULL")
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
    )


def _json_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


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

_GENERATED_ARTIFACT_INDEX_SCHEMA_SQL = """
CREATE INDEX IF NOT EXISTS generated_artifacts_user_created_idx
    ON generated_artifacts (user_id, permission_version, created_at DESC);

CREATE INDEX IF NOT EXISTS generated_artifacts_session_idx
    ON generated_artifacts (session_id, user_id, permission_version);

CREATE UNIQUE INDEX IF NOT EXISTS generated_artifacts_job_format_uidx
    ON generated_artifacts (job_id, artifact_format)
    WHERE job_id IS NOT NULL;
"""

GENERATED_ARTIFACT_SCHEMA_SQL = _GENERATED_ARTIFACT_TABLE_SCHEMA_SQL + _GENERATED_ARTIFACT_INDEX_SCHEMA_SQL
