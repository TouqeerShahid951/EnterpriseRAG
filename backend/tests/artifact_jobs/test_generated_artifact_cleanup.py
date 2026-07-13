from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rag.artifact_jobs.adapters.generated_memory import InMemoryGeneratedArtifactRepository
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.adapters.storage import LocalGeneratedArtifactStorage
from rag.artifact_jobs.cleanup import GeneratedArtifactCleanupError, GeneratedArtifactCleanupService

from generated_artifact_lifecycle_support import (
    FailOnceDeleteRepository,
    FailingDeleteStorage,
    create_artifact,
    create_job,
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
    expired = create_artifact(
        repository,
        job_id="expired-job",
        object_path=stored.object_path,
        expires_at=cutoff,
    )
    missing = create_artifact(
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
    future = create_artifact(
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
    expired = create_artifact(
        repository,
        job_id="retry-job",
        object_path=stored.object_path,
        expires_at=cutoff,
    )
    fail_once = FailOnceDeleteRepository(repository)
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
    failed_job = create_job(jobs, "storage-failure-job", retention_days=1)
    empty_job = create_job(jobs, "unrelated-empty-job", retention_days=1)
    expired = create_artifact(
        repository,
        job_id=failed_job.id,
        object_path="generated-artifacts/expired.pdf",
        expires_at=cutoff,
    )
    service = GeneratedArtifactCleanupService(
        repository_factory=lambda: repository,
        storage_factory=FailingDeleteStorage,
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
    expired_job = create_job(jobs, "expired-with-file", retention_days=1)
    empty_job = create_job(jobs, "expired-empty", retention_days=1)
    blocked_job = create_job(jobs, "expired-linked-future", retention_days=1)
    future_job = create_job(jobs, "future", retention_days=5)
    stored = storage.put(
        filename="expired.pdf",
        content=b"expired",
        content_type="application/pdf",
        object_key="cleanup/job-expired.pdf",
    )
    expired_artifact = create_artifact(
        repository,
        job_id=expired_job.id,
        object_path=stored.object_path,
        expires_at=expired_job.expires_at,
    )
    blocked_artifact = create_artifact(
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
    record = create_artifact(
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
    expired = create_artifact(
        repository,
        job_id="expired-job",
        object_path=stored.object_path,
        expires_at=cutoff,
    )
    live = create_artifact(
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
