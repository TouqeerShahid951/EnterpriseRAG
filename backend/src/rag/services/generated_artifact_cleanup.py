"""Retry-safe cleanup for expired artifact files, metadata, and job records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from ..repositories.artifact_jobs import ArtifactJobRepository
from ..repositories.generated_artifact_models import GeneratedArtifactRepository
from .generated_artifact_storage import GeneratedArtifactStorage


CleanupFailureStage = Literal[
    "repository_list",
    "repository_read",
    "repository_reference",
    "storage_list",
    "storage_delete",
    "repository_delete",
    "job_repository_list",
    "job_artifact_list",
    "job_repository_delete",
]


@dataclass(frozen=True)
class GeneratedArtifactCleanupFailure:
    stage: CleanupFailureStage
    error_type: str
    message: str
    artifact_id: str | None = None
    object_path: str | None = None


@dataclass(frozen=True)
class GeneratedArtifactCleanupResult:
    scanned_count: int
    deleted_count: int
    missing_object_count: int
    skipped_count: int
    scanned_job_count: int = 0
    deleted_job_count: int = 0
    skipped_job_count: int = 0
    scanned_orphan_count: int = 0
    deleted_orphan_count: int = 0
    skipped_orphan_count: int = 0
    failures: tuple[GeneratedArtifactCleanupFailure, ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.failures


class GeneratedArtifactCleanupError(RuntimeError):
    def __init__(self, result: GeneratedArtifactCleanupResult) -> None:
        super().__init__(
            f"generated artifact cleanup failed for {len(result.failures)} operation(s)"
        )
        self.result = result


class GeneratedArtifactCleanupService:
    def __init__(
        self,
        *,
        repository_factory: Callable[[], GeneratedArtifactRepository],
        storage_factory: Callable[[], GeneratedArtifactStorage],
        job_repository_factory: Callable[[], ArtifactJobRepository] | None = None,
        orphan_grace_period: timedelta = timedelta(days=1),
    ) -> None:
        if orphan_grace_period < timedelta(0):
            raise ValueError("orphan_grace_period must not be negative")
        self._repository_factory = repository_factory
        self._storage_factory = storage_factory
        self._job_repository_factory = job_repository_factory
        self._orphan_grace_period = orphan_grace_period

    def cleanup_expired(
        self,
        *,
        as_of: datetime | None = None,
        limit: int = 100,
    ) -> GeneratedArtifactCleanupResult:
        cutoff = as_of or datetime.now(UTC)
        _validate_cutoff(cutoff)
        if limit < 1:
            raise ValueError("limit must be positive")

        repository = self._repository_factory()
        storage = self._storage_factory()
        try:
            expired = repository.list_expired_artifacts(
                expires_before=cutoff, limit=limit
            )
        except Exception as exc:
            result = GeneratedArtifactCleanupResult(
                scanned_count=0,
                deleted_count=0,
                missing_object_count=0,
                skipped_count=0,
                failures=(_failure("repository_list", exc),),
            )
            raise GeneratedArtifactCleanupError(result) from exc

        deleted_count = 0
        missing_object_count = 0
        skipped_count = 0
        scanned_job_count = 0
        deleted_job_count = 0
        skipped_job_count = 0
        scanned_orphan_count = 0
        deleted_orphan_count = 0
        skipped_orphan_count = 0
        failures: list[GeneratedArtifactCleanupFailure] = []
        for artifact in expired:
            try:
                current = repository.get_artifact(artifact.id)
            except Exception as exc:
                failures.append(
                    _failure("repository_read", exc, artifact.id, artifact.object_path)
                )
                continue
            if (
                current is None
                or current.object_path != artifact.object_path
                or current.expires_at is None
                or current.expires_at > cutoff
            ):
                skipped_count += 1
                continue
            try:
                referenced_elsewhere = repository.is_object_path_referenced(
                    artifact.object_path,
                    excluding_artifact_id=artifact.id,
                )
            except Exception as exc:
                failures.append(
                    _failure(
                        "repository_reference", exc, artifact.id, artifact.object_path
                    )
                )
                continue
            if not referenced_elsewhere:
                try:
                    object_deleted = storage.delete(artifact.object_path)
                except Exception as exc:
                    failures.append(
                        _failure(
                            "storage_delete", exc, artifact.id, artifact.object_path
                        )
                    )
                    continue
                if not object_deleted:
                    missing_object_count += 1
            try:
                metadata_deleted = repository.delete_expired_artifact(
                    artifact.id,
                    expires_before=cutoff,
                    expected_object_path=artifact.object_path,
                )
            except Exception as exc:
                failures.append(
                    _failure(
                        "repository_delete", exc, artifact.id, artifact.object_path
                    )
                )
                continue
            if metadata_deleted:
                deleted_count += 1
            else:
                skipped_count += 1

        if self._job_repository_factory is not None:
            jobs = self._job_repository_factory()
            try:
                expired_jobs = jobs.list_expired_jobs(
                    expires_before=cutoff, limit=limit
                )
            except Exception as exc:
                failures.append(_failure("job_repository_list", exc))
                expired_jobs = []
            scanned_job_count = len(expired_jobs)
            for job in expired_jobs:
                try:
                    linked_artifacts = repository.list_artifacts_for_job(job.id)
                except Exception as exc:
                    failures.append(_failure("job_artifact_list", exc, job.id))
                    continue
                if linked_artifacts:
                    skipped_job_count += 1
                    continue
                try:
                    job_deleted = jobs.delete_expired_job(
                        job.id,
                        expires_before=cutoff,
                    )
                except Exception as exc:
                    failures.append(_failure("job_repository_delete", exc, job.id))
                    continue
                if job_deleted:
                    deleted_job_count += 1
                else:
                    skipped_job_count += 1

        list_objects = getattr(storage, "list_objects", None)
        if callable(list_objects):
            try:
                orphan_candidates = list_objects(
                    modified_before=cutoff - self._orphan_grace_period,
                    limit=limit,
                )
            except Exception as exc:
                failures.append(_failure("storage_list", exc))
                orphan_candidates = []
            scanned_orphan_count = len(orphan_candidates)
            for object_path in orphan_candidates:
                try:
                    referenced = repository.is_object_path_referenced(object_path)
                except Exception as exc:
                    failures.append(
                        _failure("repository_reference", exc, object_path=object_path)
                    )
                    continue
                if referenced:
                    skipped_orphan_count += 1
                    continue
                try:
                    orphan_deleted = storage.delete(object_path)
                except Exception as exc:
                    failures.append(
                        _failure("storage_delete", exc, object_path=object_path)
                    )
                    continue
                if orphan_deleted:
                    deleted_orphan_count += 1
                else:
                    skipped_orphan_count += 1

        result = GeneratedArtifactCleanupResult(
            scanned_count=len(expired),
            deleted_count=deleted_count,
            missing_object_count=missing_object_count,
            skipped_count=skipped_count,
            scanned_job_count=scanned_job_count,
            deleted_job_count=deleted_job_count,
            skipped_job_count=skipped_job_count,
            scanned_orphan_count=scanned_orphan_count,
            deleted_orphan_count=deleted_orphan_count,
            skipped_orphan_count=skipped_orphan_count,
            failures=tuple(failures),
        )
        if failures:
            raise GeneratedArtifactCleanupError(result)
        return result


def default_generated_artifact_cleanup_service() -> GeneratedArtifactCleanupService:
    from ..repositories.artifact_jobs import get_artifact_job_repository
    from ..repositories.generated_artifacts import get_generated_artifact_repository
    from .generated_artifact_storage import get_generated_artifact_storage

    return GeneratedArtifactCleanupService(
        repository_factory=get_generated_artifact_repository,
        storage_factory=get_generated_artifact_storage,
        job_repository_factory=get_artifact_job_repository,
    )


def cleanup_expired_generated_artifacts(
    *,
    as_of: datetime | None = None,
    limit: int = 100,
) -> GeneratedArtifactCleanupResult:
    """Run one bounded cleanup batch for a scheduler or maintenance command."""

    return default_generated_artifact_cleanup_service().cleanup_expired(
        as_of=as_of, limit=limit
    )


def _failure(
    stage: CleanupFailureStage,
    exc: Exception,
    artifact_id: str | None = None,
    object_path: str | None = None,
) -> GeneratedArtifactCleanupFailure:
    return GeneratedArtifactCleanupFailure(
        stage=stage,
        error_type=type(exc).__name__,
        message=str(exc)[:500],
        artifact_id=artifact_id,
        object_path=object_path,
    )


def _validate_cutoff(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
