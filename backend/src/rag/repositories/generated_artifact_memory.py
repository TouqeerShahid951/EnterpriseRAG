"""In-memory generated artifact repository for tests and local fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .generated_artifact_models import GeneratedArtifactRecord


class InMemoryGeneratedArtifactRepository:
    def __init__(self) -> None:
        self._artifacts: dict[str, GeneratedArtifactRecord] = {}

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
        if job_id:
            existing = next(
                (
                    artifact
                    for artifact in self._artifacts.values()
                    if artifact.job_id == job_id and artifact.format == format
                ),
                None,
            )
            if existing is not None:
                return existing
        record = GeneratedArtifactRecord(
            id=str(uuid4()),
            job_id=job_id,
            user_id=user_id,
            permission_version=permission_version,
            session_id=session_id,
            trace_id=trace_id,
            requested_formats=tuple(requested_formats),
            filename=filename,
            format=format,
            content_type=content_type,
            object_path=object_path,
            size_bytes=size_bytes,
            source_doc_ids=tuple(source_doc_ids),
            prompt=prompt,
            created_at=datetime.now(UTC),
        )
        self._artifacts[record.id] = record
        return record

    def get_artifact(self, artifact_id: str) -> GeneratedArtifactRecord | None:
        return self._artifacts.get(artifact_id)

    def list_artifacts_for_job(self, job_id: str) -> list[GeneratedArtifactRecord]:
        return sorted(
            (artifact for artifact in self._artifacts.values() if artifact.job_id == job_id),
            key=lambda artifact: artifact.created_at or datetime.min.replace(tzinfo=UTC),
        )
