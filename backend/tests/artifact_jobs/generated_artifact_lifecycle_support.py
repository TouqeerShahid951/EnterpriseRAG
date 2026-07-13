"""Shared builders and fakes for generated-artifact lifecycle tests."""

from __future__ import annotations

from datetime import UTC, datetime

from rag.artifact_jobs.adapters.generated_memory import InMemoryGeneratedArtifactRepository
from rag.artifact_jobs.adapters.generated_postgres import PostgresGeneratedArtifactRepository
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository


def create_job(
    repository: InMemoryArtifactJobRepository,
    client_request_id: str,
    *,
    retention_days: int,
):
    return repository.create_job(
        client_request_id=client_request_id,
        user_id="user-1",
        permission_version=1,
        user_email="user@example.test",
        account_type="platform_admin",
        group_paths=["/"],
        clearance_level="NATO_RESTRICTED",
        session_id="session-1",
        trace_id=f"trace-{client_request_id}",
        original_request="Create a report.",
        requested_formats=["pdf"],
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=retention_days,
    )


def create_artifact(
    repository: InMemoryGeneratedArtifactRepository,
    *,
    job_id: str | None,
    object_path: str,
    expires_at: datetime | None,
    filename: str = "artifact.pdf",
    size_bytes: int = 8,
):
    return repository.create_artifact(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename=filename,
        format="pdf",
        content_type="application/pdf",
        object_path=object_path,
        size_bytes=size_bytes,
        source_doc_ids=["doc-1"],
        prompt="Generate a report.",
        job_id=job_id,
        expires_at=expires_at,
    )


class FailOnceDeleteRepository:
    def __init__(self, repository: InMemoryGeneratedArtifactRepository) -> None:
        self._repository = repository
        self._failed = False

    def __getattr__(self, name: str):
        return getattr(self._repository, name)

    def delete_expired_artifact(self, *args, **kwargs) -> bool:
        if not self._failed:
            self._failed = True
            raise RuntimeError("database temporarily unavailable")
        return self._repository.delete_expired_artifact(*args, **kwargs)


class FailingDeleteStorage:
    def delete(self, _object_path: str) -> bool:
        raise RuntimeError("object store temporarily unavailable")


class CapturingPostgresRepository(PostgresGeneratedArtifactRepository):
    def __init__(self, *, default_retention_days: int) -> None:
        self.database_url = "postgresql://unused"
        self.default_retention_days = default_retention_days
        self.query = ""
        self.params: tuple[object, ...] = ()

    def _execute_one(self, query: str, params: tuple[object, ...]):
        self.query = query
        self.params = params
        expires_at = params[-3]
        return {
            "id": "artifact-1",
            "job_id": "job-1",
            "user_id": "user-1",
            "permission_version": 1,
            "session_id": "session-1",
            "trace_id": "trace-1",
            "requested_formats": ["pdf"],
            "filename": "artifact.pdf",
            "artifact_format": "pdf",
            "content_type": "application/pdf",
            "object_path": "generated-artifacts/artifact.pdf",
            "size_bytes": 8,
            "source_doc_ids": ["doc-1"],
            "prompt": "Generate a report.",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "expires_at": expires_at,
        }


class CapturingGuardedPostgresRepository(PostgresGeneratedArtifactRepository):
    def __init__(self, *, default_retention_days: int) -> None:
        self.database_url = "postgresql://unused"
        self.default_retention_days = default_retention_days
        self.query = ""
        self.params: tuple[object, ...] = ()

    def _execute_optional(self, query: str, params: tuple[object, ...]):
        self.query = query
        self.params = params
        return None
