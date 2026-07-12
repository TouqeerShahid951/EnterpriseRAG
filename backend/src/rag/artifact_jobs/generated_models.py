"""Generated artifact repository contracts and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class GeneratedArtifactRecord:
    id: str
    job_id: str | None
    user_id: str
    permission_version: int
    session_id: str
    trace_id: str
    requested_formats: tuple[str, ...]
    filename: str
    format: str
    content_type: str
    object_path: str
    size_bytes: int
    source_doc_ids: tuple[str, ...]
    prompt: str
    created_at: datetime | None
    expires_at: datetime | None = None


class GeneratedArtifactRepository(Protocol):
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
    ) -> GeneratedArtifactRecord: ...

    def get_artifact(self, artifact_id: str) -> GeneratedArtifactRecord | None: ...
    def list_artifacts_for_job(self, job_id: str) -> list[GeneratedArtifactRecord]: ...
    def delete_artifact(
        self,
        artifact_id: str,
        *,
        expected_object_path: str,
    ) -> bool: ...
    def is_object_path_referenced(
        self,
        object_path: str,
        *,
        excluding_artifact_id: str | None = None,
    ) -> bool: ...
    def list_expired_artifacts(
        self,
        *,
        expires_before: datetime,
        limit: int = 100,
    ) -> list[GeneratedArtifactRecord]: ...
    def delete_expired_artifact(
        self,
        artifact_id: str,
        *,
        expires_before: datetime,
        expected_object_path: str,
    ) -> bool: ...
