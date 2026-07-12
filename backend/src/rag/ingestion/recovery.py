"""Shared stale-ingestion detection and recovery behavior."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..repositories.document_models import DocumentRecord, DocumentRepository
from ..repositories.ingest_job_models import IngestJobRecord, IngestJobRepository
from .contracts import IngestJobPayload
from .queue import IngestQueue

MAX_INGEST_ATTEMPTS = 3


@dataclass(frozen=True)
class StaleIngestJob:
    job: IngestJobRecord
    document: DocumentRecord | None
    last_activity_at: datetime | None
    stale_for_seconds: int
    recoverable: bool
    recovery_code: str | None
    recovery_message: str


class IngestRecoveryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def list_stale_ingest_jobs(
    *,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    active_job_ids: frozenset[str] = frozenset(),
    stale_after_seconds: int,
    max_attempts: int = MAX_INGEST_ATTEMPTS,
    now: datetime | None = None,
) -> list[StaleIngestJob]:
    observed_at = now or datetime.now(UTC)
    cutoff = observed_at - timedelta(seconds=stale_after_seconds)
    stale_jobs: list[StaleIngestJob] = []
    for job in job_repo.list_ingest_jobs():
        if job.status != "processing" or job.id in active_job_ids or not is_stale_ingest_job(job, cutoff):
            continue
        document = document_repo.get_document(job.doc_id, include_deleted=True)
        active_document = document_repo.get_document(job.doc_id)
        last_activity = ingest_job_last_activity(job)
        stale_for_seconds = max(0, int((observed_at - last_activity).total_seconds())) if last_activity else stale_after_seconds
        if job.attempt_count >= max_attempts:
            code = "retry_exhausted"
            message = f"Retry limit reached ({max_attempts} attempts). Investigate the failure before starting a new ingestion."
        elif active_document is None or not active_document.file_path:
            code = "recovery_source_unavailable"
            message = "The source document is unavailable, so this job cannot be safely requeued."
        else:
            code = None
            message = f"Ready to requeue for attempt {job.attempt_count + 1} of {max_attempts}."
        stale_jobs.append(
            StaleIngestJob(
                job=job,
                document=document,
                last_activity_at=last_activity,
                stale_for_seconds=stale_for_seconds,
                recoverable=code is None,
                recovery_code=code,
                recovery_message=message,
            )
        )
    return stale_jobs


def requeue_stale_ingest_job(
    *,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
    job_id: str,
    active_job_ids: frozenset[str] = frozenset(),
    stale_after_seconds: int,
    actor_id: str | None,
    audit_event_type: str,
    max_attempts: int = MAX_INGEST_ATTEMPTS,
    now: datetime | None = None,
) -> IngestJobRecord:
    observed_at = now or datetime.now(UTC)
    job = job_repo.get_ingest_job(job_id)
    if job is None:
        raise IngestRecoveryError("job_not_found", "Ingestion job was not found.")
    if job.status != "processing":
        raise IngestRecoveryError("job_not_processing", "Only processing jobs can be recovered.")
    if job.id in active_job_ids:
        raise IngestRecoveryError("job_still_active", "The worker still reports this job as active.")

    cutoff = observed_at - timedelta(seconds=stale_after_seconds)
    if not is_stale_ingest_job(job, cutoff):
        raise IngestRecoveryError("job_not_stale", "The job has a recent heartbeat and cannot be requeued.")
    if job.attempt_count >= max_attempts:
        raise IngestRecoveryError("retry_exhausted", "The job has reached the ingestion retry limit.")

    document = document_repo.get_document(job.doc_id)
    if document is None or not document.file_path:
        raise IngestRecoveryError(
            "recovery_source_unavailable",
            "The source document is unavailable for ingestion recovery.",
        )

    requeued = job_repo.requeue_stale_ingest_job(
        job.id,
        stale_before=cutoff,
        max_attempts=max_attempts,
    )
    if requeued is None:
        raise IngestRecoveryError(
            "job_state_changed",
            "The job changed while recovery was requested. Refresh ingestion health and try again.",
        )

    queue.enqueue(ingest_queue_message(document, job))
    document_repo.append_audit_event(
        event_type=audit_event_type,
        actor_id=actor_id,
        target_type="ingest_job",
        target_id=job.id,
        payload={
            "doc_id": job.doc_id,
            "attempt_count": job.attempt_count,
            "next_attempt": job.attempt_count + 1,
            "stale_after_seconds": stale_after_seconds,
        },
    )
    return requeued


def is_stale_ingest_job(job: IngestJobRecord, cutoff: datetime) -> bool:
    timestamp = ingest_job_last_activity(job)
    return timestamp is None or timestamp < cutoff


def ingest_job_last_activity(job: IngestJobRecord) -> datetime | None:
    return job.last_heartbeat_at or job.updated_at or job.created_at


def ingest_queue_message(document: DocumentRecord, job: IngestJobRecord) -> IngestJobPayload:
    content_type, _ = mimetypes.guess_type(document.file_path or "")
    return IngestJobPayload(
        job_id=job.id,
        doc_id=document.id,
        file_path=document.file_path or "",
        group_path=document.group_path,
        clearance_level=document.clearance_level,
        acl_group_paths=list(document.access_group_paths),
        doc_type=document.doc_type,
        effective_date=document.effective_date.isoformat() if document.effective_date else None,
        supersedes=list(document.pending_supersedes),
        expiry_date=document.expiry_date.isoformat() if document.expiry_date else None,
        description=document.description,
        content_type=content_type,
    )
