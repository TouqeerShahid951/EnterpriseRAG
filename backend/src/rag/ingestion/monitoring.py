"""Application services for ingestion history and stale-job recovery."""

from __future__ import annotations

from dataclasses import dataclass

from ..documents.models import DocumentRepository
from .job_models import (
    IngestJobAccess,
    IngestJobFilters,
    IngestJobPage,
    IngestJobRecord,
    IngestJobRepository,
    IngestJobSearchRepository,
    IngestJobSummary,
)
from .queue import IngestQueue
from .recovery import (
    StaleIngestJob,
    list_stale_ingest_jobs,
    requeue_stale_ingest_job,
)
from .worker_control import IngestWorkerControl, WorkerControlResult

@dataclass(frozen=True)
class StaleIngestJobOverview:
    candidates: tuple[StaleIngestJob, ...]
    stale_after_seconds: int

    @property
    def recoverable(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.recoverable)


class IngestWorkerStatusUnavailable(RuntimeError):
    """Raised when stale-job recovery cannot safely inspect active workers."""


def search_visible_ingest_jobs(
    *,
    repo: IngestJobSearchRepository,
    access: IngestJobAccess,
    filters: IngestJobFilters,
    can_view: bool,
    limit: int,
    offset: int,
) -> IngestJobPage:
    """Return one access-scoped page without exposing transport concerns."""

    if not can_view:
        return IngestJobPage(items=(), total=0)
    return repo.search_visible_ingest_jobs(
        access=access,
        filters=filters,
        limit=limit,
        offset=offset,
    )


def summarize_visible_ingest_jobs(
    *,
    repo: IngestJobSearchRepository,
    access: IngestJobAccess,
    filters: IngestJobFilters,
    can_view: bool,
) -> IngestJobSummary:
    """Summarize all jobs visible through the supplied access scope."""

    if not can_view:
        return IngestJobSummary()
    return repo.summarize_visible_ingest_jobs(
        access=access,
        filters=filters,
    )


def inspect_stale_ingest_jobs(
    *,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    control: IngestWorkerControl,
    desired_concurrency: int,
    stale_after_seconds: int,
) -> StaleIngestJobOverview:
    """List stale jobs only after worker activity has been verified."""

    snapshot = require_worker_snapshot(control, desired_concurrency)
    candidates = list_stale_ingest_jobs(
        document_repo=document_repo,
        job_repo=job_repo,
        active_job_ids=snapshot.active_job_ids,
        stale_after_seconds=stale_after_seconds,
    )
    return StaleIngestJobOverview(
        candidates=tuple(candidates),
        stale_after_seconds=stale_after_seconds,
    )


def requeue_stale_job(
    *,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
    control: IngestWorkerControl,
    desired_concurrency: int,
    stale_after_seconds: int,
    job_id: str,
    actor_id: str | None,
    audit_event_type: str,
) -> IngestJobRecord:
    """Safely requeue one stale job after excluding active worker tasks."""

    snapshot = require_worker_snapshot(control, desired_concurrency)
    return requeue_stale_ingest_job(
        document_repo=document_repo,
        job_repo=job_repo,
        queue=queue,
        job_id=job_id,
        active_job_ids=snapshot.active_job_ids,
        stale_after_seconds=stale_after_seconds,
        actor_id=actor_id,
        audit_event_type=audit_event_type,
    )


def require_worker_snapshot(
    control: IngestWorkerControl,
    desired_concurrency: int,
) -> WorkerControlResult:
    try:
        return control.snapshot(desired_concurrency)
    except Exception as exc:
        raise IngestWorkerStatusUnavailable from exc
