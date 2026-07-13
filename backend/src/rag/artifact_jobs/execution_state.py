"""Authorization, lease, diagnostics, and timing state for artifact execution."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import logging
from time import perf_counter

from ..auth.document_access import can_read_document
from ..auth.identity_models import IdentityRepository, UserRecord
from ..documents.models import DocumentRepository
from .execution_errors import (
    ArtifactJobCancelled,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
)
from .job_models import ArtifactJobRecord, ArtifactJobRepository


logger = logging.getLogger("rag.artifact_jobs")


class ArtifactExecutionState:
    """Own the mutable job state used by an artifact execution attempt."""

    repo_factory: Callable[[], ArtifactJobRepository]
    identity_repo_factory: Callable[[], IdentityRepository]
    document_repo_factory: Callable[[], DocumentRepository]
    _run_token: str | None

    def _authorize(
        self,
        job: ArtifactJobRecord,
        additional_document_ids: list[str] | tuple[str, ...] = (),
    ) -> UserRecord:
        user = self.identity_repo_factory().get_user_by_id(job.user_id)
        if (
            user is None
            or not user.is_active
            or user.permission_version != job.permission_version
        ):
            raise ArtifactPermissionChanged(
                "artifact job authorization is no longer valid"
            )
        document_repo = self.document_repo_factory()
        document_ids = dict.fromkeys((*job.document_ids, *additional_document_ids))
        for document_id in document_ids:
            document = document_repo.get_document(document_id)
            if document is None or not can_read_document(user, document):
                raise ArtifactPermissionChanged(
                    "artifact job document access is no longer valid"
                )
        return user

    def _guard_publication(
        self,
        job: ArtifactJobRecord,
        source_doc_ids: list[str],
    ) -> None:
        self._check_cancelled(job.id)
        self._authorize(job, source_doc_ids)

    def _check_cancelled(self, job_id: str) -> None:
        current = self.repo_factory().get_job(job_id)
        if current is None:
            raise RuntimeError("artifact job was not found")
        if current.cancellation_requested or current.status == "cancelled":
            raise ArtifactJobCancelled("artifact job was cancelled")
        if current.expires_at is not None and current.expires_at <= datetime.now(UTC):
            raise ArtifactJobCancelled("artifact job expired")
        run_token = getattr(self, "_run_token", None)
        if run_token is not None and current.run_token != run_token:
            raise ArtifactJobLeaseLost("artifact job execution lease was reclaimed")

    def _update(self, job_id: str, changes: dict[str, object]) -> ArtifactJobRecord:
        repo = self.repo_factory()
        run_token = getattr(self, "_run_token", None)
        updated = (
            repo.transition_job(job_id, run_token=run_token, changes=changes)
            if run_token is not None
            else repo.update_job(job_id, changes)
        )
        if updated is None:
            current = repo.get_job(job_id)
            if current is None:
                raise RuntimeError("artifact job was not found")
            if current.cancellation_requested or current.status == "cancelled":
                raise ArtifactJobCancelled("artifact job was cancelled")
            raise ArtifactJobLeaseLost("artifact job execution lease was reclaimed")
        return updated

    @contextmanager
    def _stage_timer(
        self, job_id: str, stage: str, *, accumulate: bool = False
    ) -> Iterator[None]:
        started_at = datetime.now(UTC)
        started_perf = perf_counter()
        try:
            yield
        finally:
            try:
                self._record_stage_timing(
                    job_id,
                    stage,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    duration_ms=int((perf_counter() - started_perf) * 1000),
                    accumulate=accumulate,
                )
            except Exception:
                logger.warning(
                    "failed to record artifact stage timing job_id=%s stage=%s",
                    job_id,
                    stage,
                    exc_info=True,
                )

    def _record_stage_timing(
        self,
        job_id: str,
        stage: str,
        *,
        started_at: datetime,
        completed_at: datetime,
        duration_ms: int,
        accumulate: bool,
    ) -> None:
        repo = self.repo_factory()
        current = repo.get_job(job_id)
        if current is None:
            return
        timings = dict(current.stage_timings_json)
        timing: dict[str, object] = {
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": max(0, duration_ms),
        }
        existing = timings.get(stage)
        if accumulate and isinstance(existing, dict):
            timing["started_at"] = str(
                existing.get("started_at") or timing["started_at"]
            )
            try:
                timing["duration_ms"] = int(existing.get("duration_ms") or 0) + int(
                    timing["duration_ms"]
                )
            except (TypeError, ValueError):
                pass
        timings[stage] = timing
        self._update(job_id, {"stage_timings_json": timings})

    def _record_error(
        self,
        job_id: str,
        *,
        stage: str,
        code: str,
        message: str,
        context: dict[str, object] | None = None,
    ) -> None:
        repo = self.repo_factory()
        current = repo.get_job(job_id)
        if current is None:
            return
        errors = list(current.errors_json)
        errors.append(
            {
                "stage": stage,
                "code": code,
                "message": message[:2000],
                "context": context or {},
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        )
        self._update(job_id, {"errors_json": errors[-50:]})
