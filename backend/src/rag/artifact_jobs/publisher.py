"""Idempotent publication of rendered artifact files and metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
import logging

from ..documents.models import DocumentRepository
from ..services.generated_artifact_storage import GeneratedArtifactStorage
from .generated_models import (
    GeneratedArtifactRecord,
    GeneratedArtifactRepository,
)
from .job_models import ArtifactJobRecord


logger = logging.getLogger("rag.artifact_jobs.publisher")


@dataclass(frozen=True)
class PublishedArtifact:
    record: GeneratedArtifactRecord
    warnings: tuple[str, ...] = ()


class ArtifactPublisher:
    def __init__(
        self,
        *,
        artifact_repo_factory: Callable[[], GeneratedArtifactRepository],
        storage_factory: Callable[[], GeneratedArtifactStorage],
        audit_repo_factory: Callable[[], DocumentRepository],
    ) -> None:
        self._artifact_repo_factory = artifact_repo_factory
        self._storage_factory = storage_factory
        self._audit_repo_factory = audit_repo_factory

    def publish(
        self,
        *,
        job: ArtifactJobRecord,
        filename: str,
        artifact_format: str,
        content_type: str,
        content: bytes,
        source_doc_ids: list[str],
        smoke_warnings: list[str],
        expected_run_token: str | None = None,
        lease_guard: Callable[[], None] | None = None,
    ) -> PublishedArtifact:
        guard = lease_guard or _no_op
        guard()
        repository = self._artifact_repo_factory()
        storage = self._storage_factory()
        previous = next(
            (
                artifact
                for artifact in repository.list_artifacts_for_job(job.id)
                if artifact.format == artifact_format
            ),
            None,
        )
        content_digest = sha256(content).hexdigest()
        attempt_key = (
            sha256(expected_run_token.encode("utf-8")).hexdigest()[:16]
            if expected_run_token
            else content_digest[:16]
        )
        stored = storage.put(
            filename=filename,
            content=content,
            content_type=content_type,
            object_key=(
                f"jobs/{job.id}/{artifact_format}/"
                f"{attempt_key}-{content_digest[:24]}.{artifact_format}"
            ),
        )
        try:
            guard()
            record = repository.create_artifact(
                job_id=job.id,
                user_id=job.user_id,
                permission_version=job.permission_version,
                session_id=job.session_id,
                trace_id=job.trace_id,
                requested_formats=list(job.requested_formats),
                filename=filename,
                format=artifact_format,
                content_type=content_type,
                object_path=stored.object_path,
                size_bytes=stored.size_bytes,
                source_doc_ids=source_doc_ids,
                prompt=job.original_request,
                expires_at=job.expires_at,
                expected_job_run_token=expected_run_token,
            )
        except Exception:
            if previous is None or previous.object_path != stored.object_path:
                _delete_after_failed_publish(repository, storage, stored.object_path)
            raise

        warnings = list(smoke_warnings)
        if previous is not None and previous.object_path != stored.object_path:
            try:
                storage.delete(previous.object_path)
            except Exception as exc:
                warnings.append(
                    f"Previous artifact cleanup failed: {type(exc).__name__}"
                )
                logger.warning(
                    "previous generated artifact cleanup failed job_id=%s format=%s object_path=%s",
                    job.id,
                    artifact_format,
                    previous.object_path,
                    exc_info=True,
                )
        try:
            self._audit_repo_factory().append_audit_event(
                event_type="query.artifact_created",
                actor_id=job.user_id,
                target_type="generated_artifact",
                target_id=record.id,
                payload={
                    "artifact_job_id": job.id,
                    "format": artifact_format,
                    "source_doc_ids": source_doc_ids,
                    "smoke_warnings": smoke_warnings,
                },
            )
        except Exception as exc:
            warnings.append(f"Artifact audit recording failed: {type(exc).__name__}")
            logger.error(
                "generated artifact audit recording failed job_id=%s artifact_id=%s format=%s",
                job.id,
                record.id,
                artifact_format,
                exc_info=True,
            )
        return PublishedArtifact(record=record, warnings=tuple(warnings))


def _delete_after_failed_publish(
    repository: GeneratedArtifactRepository,
    storage: GeneratedArtifactStorage,
    object_path: str,
) -> None:
    try:
        if repository.is_object_path_referenced(object_path):
            return
    except Exception:
        logger.error(
            "generated artifact compensation was deferred because reference checking failed "
            "object_path=%s",
            object_path,
            exc_info=True,
        )
        return
    try:
        storage.delete(object_path)
    except Exception:
        logger.error(
            "generated artifact compensation failed object_path=%s",
            object_path,
            exc_info=True,
        )


def _no_op() -> None:
    return None
