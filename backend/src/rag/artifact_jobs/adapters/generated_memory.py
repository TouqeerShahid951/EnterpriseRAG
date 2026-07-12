"""In-memory generated artifact repository for tests and local fallback."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from ..generated_models import GeneratedArtifactRecord


class InMemoryGeneratedArtifactRepository:
    def __init__(self, default_retention_days: int = 30) -> None:
        if default_retention_days < 1:
            raise ValueError("default_retention_days must be positive")
        self._artifacts: dict[str, GeneratedArtifactRecord] = {}
        self._default_retention_days = default_retention_days
        self._lock = RLock()

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
        _ = expected_job_run_token
        validated_expiry = (
            _validated_timestamp(expires_at, field_name="expires_at")
            if expires_at
            else None
        )
        with self._lock:
            existing = (
                self._find_job_format(job_id=job_id, format=format)
                if job_id
                else self._find_trace_format(
                    user_id=user_id,
                    permission_version=permission_version,
                    trace_id=trace_id,
                    format=format,
                )
            )
            if existing is not None:
                updated = replace(
                    existing,
                    filename=filename,
                    content_type=content_type,
                    object_path=object_path,
                    size_bytes=size_bytes,
                    source_doc_ids=tuple(source_doc_ids),
                    prompt=prompt,
                    expires_at=validated_expiry or existing.expires_at,
                )
                self._artifacts[existing.id] = updated
                return updated
            now = datetime.now(UTC)
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
                created_at=now,
                expires_at=validated_expiry
                or now + timedelta(days=self._default_retention_days),
            )
            self._artifacts[record.id] = record
            return record

    def get_artifact(self, artifact_id: str) -> GeneratedArtifactRecord | None:
        with self._lock:
            return self._artifacts.get(artifact_id)

    def list_artifacts_for_job(self, job_id: str) -> list[GeneratedArtifactRecord]:
        with self._lock:
            return sorted(
                (
                    artifact
                    for artifact in self._artifacts.values()
                    if artifact.job_id == job_id
                ),
                key=lambda artifact: (
                    artifact.created_at or datetime.min.replace(tzinfo=UTC)
                ),
            )

    def delete_artifact(
        self,
        artifact_id: str,
        *,
        expected_object_path: str,
    ) -> bool:
        with self._lock:
            artifact = self._artifacts.get(artifact_id)
            if artifact is None or artifact.object_path != expected_object_path:
                return False
            del self._artifacts[artifact_id]
            return True

    def is_object_path_referenced(
        self,
        object_path: str,
        *,
        excluding_artifact_id: str | None = None,
    ) -> bool:
        with self._lock:
            return any(
                artifact.object_path == object_path
                and artifact.id != excluding_artifact_id
                for artifact in self._artifacts.values()
            )

    def list_expired_artifacts(
        self,
        *,
        expires_before: datetime,
        limit: int = 100,
    ) -> list[GeneratedArtifactRecord]:
        cutoff = _validated_timestamp(expires_before, field_name="expires_before")
        _validate_limit(limit)
        with self._lock:
            expired = (
                artifact
                for artifact in self._artifacts.values()
                if artifact.expires_at is not None and artifact.expires_at <= cutoff
            )
            return sorted(
                expired, key=lambda artifact: (artifact.expires_at, artifact.id)
            )[:limit]

    def delete_expired_artifact(
        self,
        artifact_id: str,
        *,
        expires_before: datetime,
        expected_object_path: str,
    ) -> bool:
        cutoff = _validated_timestamp(expires_before, field_name="expires_before")
        with self._lock:
            artifact = self._artifacts.get(artifact_id)
            if (
                artifact is None
                or artifact.expires_at is None
                or artifact.expires_at > cutoff
                or artifact.object_path != expected_object_path
            ):
                return False
            del self._artifacts[artifact_id]
            return True

    def _find_job_format(
        self, *, job_id: str, format: str
    ) -> GeneratedArtifactRecord | None:
        return next(
            (
                artifact
                for artifact in self._artifacts.values()
                if artifact.job_id == job_id and artifact.format == format
            ),
            None,
        )

    def _find_trace_format(
        self,
        *,
        user_id: str,
        permission_version: int,
        trace_id: str,
        format: str,
    ) -> GeneratedArtifactRecord | None:
        return next(
            (
                artifact
                for artifact in self._artifacts.values()
                if artifact.job_id is None
                and artifact.user_id == user_id
                and artifact.permission_version == permission_version
                and artifact.trace_id == trace_id
                and artifact.format == format
            ),
            None,
        )


def _validated_timestamp(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _validate_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be positive")
