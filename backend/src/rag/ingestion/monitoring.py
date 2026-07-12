"""Application services for ingestion history and stale-job recovery."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from ..documents.models import DocumentRepository
from ..documents.upload_status import stage_for_job_status
from .job_models import (
    IngestJobAccess,
    IngestJobFilters,
    IngestJobPage,
    IngestJobRecord,
    IngestJobRepository,
    IngestJobSearchRepository,
)
from .queue import IngestQueue
from .recovery import (
    StaleIngestJob,
    list_stale_ingest_jobs,
    requeue_stale_ingest_job,
)
from .worker_control import IngestWorkerControl, WorkerControlResult

ACTIVE_JOB_STATUSES = frozenset(
    {"scheduled", "queued", "processing", "human_review"}
)
ATTENTION_JOB_STATUSES = ACTIVE_JOB_STATUSES | {"failed"}
KNOWN_JOB_ORIGINS = frozenset(
    {"upload", "reingest", "restore", "folder", "connector", "unknown"}
)


@dataclass(frozen=True)
class IngestJobSummary:
    total: int = 0
    active: int = 0
    needs_attention: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    stage_counts: dict[str, int] = field(default_factory=dict)
    origin_counts: dict[str, int] = field(default_factory=dict)


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
    page = repo.search_visible_ingest_jobs(
        access=access,
        filters=filters,
        limit=None,
        offset=0,
    )
    jobs = [view.job for view in page.items]
    status_counts = _count_values(job.status for job in jobs)
    stage_counts = _count_values(_job_stage(job) for job in jobs)
    origin_counts = _count_values(_job_origin(job) for job in jobs)
    return IngestJobSummary(
        total=page.total,
        active=sum(status_counts.get(status, 0) for status in ACTIVE_JOB_STATUSES),
        needs_attention=_latest_attention_count(jobs),
        status_counts=status_counts,
        stage_counts=stage_counts,
        origin_counts=origin_counts,
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


def _job_stage(job: IngestJobRecord) -> str:
    progress = max(0, min(100, int(job.progress_pct)))
    return str(
        stage_for_job_status(
            job.status,
            progress,
            stage_progress=job.stage_progress,
        )
    )


def _job_origin(job: IngestJobRecord) -> str:
    return job.origin if job.origin in KNOWN_JOB_ORIGINS else "unknown"


def _count_values(values: Iterable[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_value in values:
        value = str(raw_value)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _latest_attention_count(jobs: list[IngestJobRecord]) -> int:
    latest_by_document: dict[str, IngestJobRecord] = {}
    for job in sorted(jobs, key=_latest_job_key, reverse=True):
        latest_by_document.setdefault(job.doc_id, job)
    return sum(
        1
        for job in latest_by_document.values()
        if job.status in ATTENTION_JOB_STATUSES
    )


def _latest_job_key(job: IngestJobRecord) -> tuple[float, str]:
    timestamps = [
        value.timestamp()
        for value in (job.created_at, job.updated_at)
        if isinstance(value, datetime)
    ]
    return (max(timestamps, default=float("-inf")), job.id)
