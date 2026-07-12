from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rag.repositories.artifact_jobs import InMemoryArtifactJobRepository
from rag.repositories.generated_artifact_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.repositories.generated_artifact_postgres import (
    PostgresGeneratedArtifactRepository,
)
from rag.services.generated_artifact_cleanup import (
    GeneratedArtifactCleanupError,
    GeneratedArtifactCleanupService,
)
from rag.services.generated_artifact_storage import LocalGeneratedArtifactStorage


def test_local_storage_stable_object_key_overwrites_atomically_and_deletes_idempotently(
    tmp_path,
) -> None:
    storage = LocalGeneratedArtifactStorage(str(tmp_path))

    first = storage.put(
        filename="Quarterly Report.docx",
        content=b"first",
        content_type="application/docx",
        object_key="jobs/job-1/report.docx",
    )
    second = storage.put(
        filename="Renamed Report.docx",
        content=b"second",
        content_type="application/docx",
        object_key="jobs/job-1/report.docx",
    )

    assert first.object_path == second.object_path
    assert Path(second.object_path).read_bytes() == b"second"
    assert storage.delete(second.object_path)
    assert not storage.delete(second.object_path)


@pytest.mark.parametrize(
    "object_key", ["", "../report.docx", "/report.docx", "jobs\\report.docx"]
)
def test_local_storage_rejects_unsafe_stable_object_keys(
    tmp_path, object_key: str
) -> None:
    storage = LocalGeneratedArtifactStorage(str(tmp_path))

    with pytest.raises(ValueError):
        storage.put(
            filename="report.docx",
            content=b"content",
            content_type="application/docx",
            object_key=object_key,
        )


def test_local_storage_default_key_remains_unique(tmp_path) -> None:
    storage = LocalGeneratedArtifactStorage(str(tmp_path))

    first = storage.put(
        filename="report.pdf", content=b"one", content_type="application/pdf"
    )
    second = storage.put(
        filename="report.pdf", content=b"two", content_type="application/pdf"
    )

    assert first.object_path != second.object_path


def test_in_memory_repository_duplicate_job_format_matches_postgres_upsert() -> None:
    repository = InMemoryGeneratedArtifactRepository(default_retention_days=7)
    initial_expiry = datetime(2026, 1, 2, tzinfo=UTC)
    first = _create_artifact(
        repository,
        job_id="job-1",
        object_path="generated-artifacts/first.docx",
        expires_at=initial_expiry,
        filename="first.docx",
        size_bytes=10,
    )

    second = _create_artifact(
        repository,
        job_id="job-1",
        object_path="generated-artifacts/second.docx",
        expires_at=None,
        filename="second.docx",
        size_bytes=20,
    )

    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.expires_at == initial_expiry
    assert second.filename == "second.docx"
    assert second.object_path == "generated-artifacts/second.docx"
    assert second.size_bytes == 20
    assert repository.list_artifacts_for_job("job-1") == [second]


def test_in_memory_repository_legacy_trace_format_is_idempotent() -> None:
    repository = InMemoryGeneratedArtifactRepository()
    first = _create_artifact(
        repository,
        job_id=None,
        object_path="generated-artifacts/query/first.pdf",
        expires_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    second = _create_artifact(
        repository,
        job_id=None,
        object_path="generated-artifacts/query/second.pdf",
        expires_at=datetime(2026, 1, 3, tzinfo=UTC),
        filename="second.pdf",
    )

    assert second.id == first.id
    assert second.filename == "second.pdf"
    assert second.object_path == "generated-artifacts/query/second.pdf"


def test_in_memory_repository_lists_and_conditionally_deletes_expired_artifacts() -> (
    None
):
    repository = InMemoryGeneratedArtifactRepository()
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    expired = _create_artifact(
        repository,
        job_id="expired-job",
        object_path="generated-artifacts/expired.pdf",
        expires_at=cutoff - timedelta(seconds=1),
    )
    _create_artifact(
        repository,
        job_id="future-job",
        object_path="generated-artifacts/future.pdf",
        expires_at=cutoff + timedelta(seconds=1),
    )

    assert repository.list_expired_artifacts(expires_before=cutoff) == [expired]
    assert not repository.delete_expired_artifact(
        expired.id,
        expires_before=cutoff,
        expected_object_path="generated-artifacts/wrong.pdf",
    )
    assert repository.delete_expired_artifact(
        expired.id,
        expires_before=cutoff,
        expected_object_path=expired.object_path,
    )
    assert repository.get_artifact(expired.id) is None


def test_postgres_upsert_carries_expiry_and_configured_default_retention() -> None:
    repository = _CapturingPostgresRepository(default_retention_days=12)
    expires_at = datetime(2026, 2, 1, tzinfo=UTC)

    record = repository.create_artifact(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename="artifact.pdf",
        format="pdf",
        content_type="application/pdf",
        object_path="generated-artifacts/artifact.pdf",
        size_bytes=8,
        source_doc_ids=["doc-1"],
        prompt="Generate a report.",
        job_id="job-1",
        expires_at=expires_at,
    )

    assert "expires_at = EXCLUDED.expires_at" in repository.query
    assert repository.params[-3:] == (expires_at, "job-1", 12)
    assert repository.query.count("%s") == len(repository.params)
    assert record.expires_at == expires_at


def test_postgres_guarded_upsert_locks_and_validates_the_worker_lease() -> None:
    repository = _CapturingGuardedPostgresRepository(default_retention_days=12)

    with pytest.raises(RuntimeError, match="publication lease"):
        repository.create_artifact(
            user_id="user-1",
            permission_version=1,
            session_id="session-1",
            trace_id="trace-1",
            requested_formats=["pdf"],
            filename="artifact.pdf",
            format="pdf",
            content_type="application/pdf",
            object_path="generated-artifacts/artifact.pdf",
            size_bytes=8,
            source_doc_ids=["doc-1"],
            prompt="Generate a report.",
            job_id="job-1",
            expires_at=datetime(2026, 2, 1, tzinfo=UTC),
            expected_job_run_token="worker-token",
        )

    assert "WITH authorized_job AS" in repository.query
    assert "FOR UPDATE" in repository.query
    assert repository.params[:2] == ("job-1", "worker-token")
    assert repository.query.count("%s") == len(repository.params)


def test_postgres_legacy_upsert_uses_trace_format_idempotency_key() -> None:
    repository = _CapturingPostgresRepository(default_retention_days=12)

    repository.create_artifact(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename="artifact.pdf",
        format="pdf",
        content_type="application/pdf",
        object_path="generated-artifacts/query/artifact.pdf",
        size_bytes=8,
        source_doc_ids=[],
        prompt="Generate a report.",
        job_id=None,
        expires_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert (
        "ON CONFLICT (user_id, permission_version, trace_id, artifact_format) "
        "WHERE job_id IS NULL" in repository.query
    )


def test_cleanup_deletes_expired_metadata_and_treats_missing_objects_as_success(
    tmp_path,
) -> None:
    repository = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    stored = storage.put(
        filename="expired.pdf",
        content=b"expired",
        content_type="application/pdf",
        object_key="cleanup/expired.pdf",
    )
    expired = _create_artifact(
        repository,
        job_id="expired-job",
        object_path=stored.object_path,
        expires_at=cutoff,
    )
    missing = _create_artifact(
        repository,
        job_id="missing-job",
        object_path=str(tmp_path / "generated-artifacts" / "missing.pdf"),
        expires_at=cutoff,
    )
    future_stored = storage.put(
        filename="future.pdf",
        content=b"future",
        content_type="application/pdf",
        object_key="cleanup/future.pdf",
    )
    future = _create_artifact(
        repository,
        job_id="future-job",
        object_path=future_stored.object_path,
        expires_at=cutoff + timedelta(days=1),
    )
    service = GeneratedArtifactCleanupService(
        repository_factory=lambda: repository,
        storage_factory=lambda: storage,
    )

    result = service.cleanup_expired(as_of=cutoff)

    assert result.scanned_count == 2
    assert result.deleted_count == 2
    assert result.missing_object_count == 1
    assert result.succeeded
    assert repository.get_artifact(expired.id) is None
    assert repository.get_artifact(missing.id) is None
    assert repository.get_artifact(future.id) == future
    assert Path(future_stored.object_path).exists()
    assert service.cleanup_expired(as_of=cutoff).scanned_count == 0


def test_cleanup_repository_failure_is_explicit_and_next_run_finishes(tmp_path) -> None:
    repository = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    stored = storage.put(
        filename="expired.pdf",
        content=b"expired",
        content_type="application/pdf",
        object_key="retry/expired.pdf",
    )
    expired = _create_artifact(
        repository,
        job_id="retry-job",
        object_path=stored.object_path,
        expires_at=cutoff,
    )
    fail_once = _FailOnceDeleteRepository(repository)
    service = GeneratedArtifactCleanupService(
        repository_factory=lambda: fail_once,
        storage_factory=lambda: storage,
    )

    with pytest.raises(GeneratedArtifactCleanupError) as caught:
        service.cleanup_expired(as_of=cutoff)

    assert caught.value.result.failures[0].stage == "repository_delete"
    assert repository.get_artifact(expired.id) is not None
    assert not Path(stored.object_path).exists()

    retried = service.cleanup_expired(as_of=cutoff)
    assert retried.deleted_count == 1
    assert retried.missing_object_count == 1
    assert repository.get_artifact(expired.id) is None


def test_cleanup_storage_failure_is_explicit_and_preserves_metadata() -> None:
    jobs = InMemoryArtifactJobRepository()
    repository = InMemoryGeneratedArtifactRepository()
    cutoff = datetime.now(UTC) + timedelta(days=2)
    failed_job = _create_job(jobs, "storage-failure-job", retention_days=1)
    empty_job = _create_job(jobs, "unrelated-empty-job", retention_days=1)
    expired = _create_artifact(
        repository,
        job_id=failed_job.id,
        object_path="generated-artifacts/expired.pdf",
        expires_at=cutoff,
    )
    service = GeneratedArtifactCleanupService(
        repository_factory=lambda: repository,
        storage_factory=_FailingDeleteStorage,
        job_repository_factory=lambda: jobs,
    )

    with pytest.raises(GeneratedArtifactCleanupError) as caught:
        service.cleanup_expired(as_of=cutoff)

    assert caught.value.result.failures[0].stage == "storage_delete"
    assert repository.get_artifact(expired.id) == expired
    assert jobs.get_job(failed_job.id) == failed_job
    assert jobs.get_job(empty_job.id) is None
    assert caught.value.result.deleted_job_count == 1


def test_cleanup_purges_expired_job_data_only_after_linked_artifacts_are_removed(
    tmp_path,
) -> None:
    jobs = InMemoryArtifactJobRepository()
    repository = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    cutoff = datetime.now(UTC) + timedelta(days=2)
    expired_job = _create_job(jobs, "expired-with-file", retention_days=1)
    empty_job = _create_job(jobs, "expired-empty", retention_days=1)
    blocked_job = _create_job(jobs, "expired-linked-future", retention_days=1)
    future_job = _create_job(jobs, "future", retention_days=5)
    stored = storage.put(
        filename="expired.pdf",
        content=b"expired",
        content_type="application/pdf",
        object_key="cleanup/job-expired.pdf",
    )
    expired_artifact = _create_artifact(
        repository,
        job_id=expired_job.id,
        object_path=stored.object_path,
        expires_at=expired_job.expires_at,
    )
    blocked_artifact = _create_artifact(
        repository,
        job_id=blocked_job.id,
        object_path=str(tmp_path / "generated-artifacts" / "future.pdf"),
        expires_at=cutoff + timedelta(days=1),
    )
    service = GeneratedArtifactCleanupService(
        repository_factory=lambda: repository,
        storage_factory=lambda: storage,
        job_repository_factory=lambda: jobs,
    )

    result = service.cleanup_expired(as_of=cutoff)

    assert result.deleted_count == 1
    assert result.scanned_job_count == 3
    assert result.deleted_job_count == 2
    assert result.skipped_job_count == 1
    assert jobs.get_job(expired_job.id) is None
    assert jobs.get_job(empty_job.id) is None
    assert jobs.get_job(blocked_job.id) == blocked_job
    assert jobs.get_job(future_job.id) == future_job
    assert repository.get_artifact(expired_artifact.id) is None
    assert repository.get_artifact(blocked_artifact.id) == blocked_artifact


def test_cleanup_reconciles_old_unreferenced_objects_and_preserves_live_references(
    tmp_path,
) -> None:
    repository = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    cutoff = datetime.now(UTC) + timedelta(seconds=1)
    orphan = storage.put(
        filename="orphan.pdf",
        content=b"orphan",
        content_type="application/pdf",
        object_key="reconcile/orphan.pdf",
    )
    referenced = storage.put(
        filename="referenced.pdf",
        content=b"referenced",
        content_type="application/pdf",
        object_key="reconcile/referenced.pdf",
    )
    record = _create_artifact(
        repository,
        job_id="future-job",
        object_path=referenced.object_path,
        expires_at=cutoff + timedelta(days=1),
    )
    service = GeneratedArtifactCleanupService(
        repository_factory=lambda: repository,
        storage_factory=lambda: storage,
        orphan_grace_period=timedelta(0),
    )

    result = service.cleanup_expired(as_of=cutoff)

    assert result.scanned_orphan_count == 2
    assert result.deleted_orphan_count == 1
    assert result.skipped_orphan_count == 1
    assert not Path(orphan.object_path).exists()
    assert Path(referenced.object_path).exists()
    assert repository.get_artifact(record.id) == record


def test_cleanup_does_not_delete_an_object_still_referenced_by_another_record(
    tmp_path,
) -> None:
    repository = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    cutoff = datetime.now(UTC)
    stored = storage.put(
        filename="shared.pdf",
        content=b"shared",
        content_type="application/pdf",
        object_key="shared/artifact.pdf",
    )
    expired = _create_artifact(
        repository,
        job_id="expired-job",
        object_path=stored.object_path,
        expires_at=cutoff,
    )
    live = _create_artifact(
        repository,
        job_id="live-job",
        object_path=stored.object_path,
        expires_at=cutoff + timedelta(days=1),
    )
    service = GeneratedArtifactCleanupService(
        repository_factory=lambda: repository,
        storage_factory=lambda: storage,
    )

    result = service.cleanup_expired(as_of=cutoff)

    assert result.deleted_count == 1
    assert Path(stored.object_path).exists()
    assert repository.get_artifact(expired.id) is None
    assert repository.get_artifact(live.id) == live


def _create_job(
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


def _create_artifact(
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


class _FailOnceDeleteRepository:
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


class _FailingDeleteStorage:
    def delete(self, _object_path: str) -> bool:
        raise RuntimeError("object store temporarily unavailable")


class _CapturingPostgresRepository(PostgresGeneratedArtifactRepository):
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


class _CapturingGuardedPostgresRepository(PostgresGeneratedArtifactRepository):
    def __init__(self, *, default_retention_days: int) -> None:
        self.database_url = "postgresql://unused"
        self.default_retention_days = default_retention_days
        self.query = ""
        self.params: tuple[object, ...] = ()

    def _execute_optional(self, query: str, params: tuple[object, ...]):
        self.query = query
        self.params = params
        return None
