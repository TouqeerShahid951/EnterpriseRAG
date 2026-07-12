"""Recover stale ingestion jobs and enforce saved worker capacity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rag.core.config import settings
from rag.repositories.document_models import DocumentRepository
from rag.repositories.documents import get_document_repository
from rag.ingestion.configuration import IngestConfigRepository
from rag.ingestion.configuration_dependencies import (
    effective_ingest_config,
    get_ingest_config_repository,
)
from rag.repositories.ingest_job_models import IngestJobRecord, IngestJobRepository
from rag.repositories.ingest_jobs import ingest_job_repository_for

from .queue import IngestQueue, get_ingest_queue
from .recovery import (
    IngestRecoveryError,
    MAX_INGEST_ATTEMPTS,
    list_stale_ingest_jobs,
    requeue_stale_ingest_job,
)
from .worker_control import IngestWorkerControl, get_ingest_worker_control


MAX_ATTEMPTS = MAX_INGEST_ATTEMPTS


def reconcile_ingestion_jobs(
    *,
    document_repo: DocumentRepository | None = None,
    job_repo: IngestJobRepository | None = None,
    queue: IngestQueue | None = None,
    control: IngestWorkerControl | None = None,
    config_repo: IngestConfigRepository | None = None,
    now: datetime | None = None,
) -> list[str]:
    document_repo = document_repo or get_document_repository()
    job_repo = job_repo or ingest_job_repository_for(document_repo)
    queue = queue or get_ingest_queue()
    control = control or get_ingest_worker_control()
    config = effective_ingest_config(
        repo=config_repo or get_ingest_config_repository()
    )
    snapshot = control.apply(config.worker_concurrency)
    observed_at = now or datetime.now(UTC)
    stale_before = observed_at - timedelta(
        seconds=settings.ingest_stale_after_seconds
    )
    recovered: list[str] = []

    stale_jobs = list_stale_ingest_jobs(
        document_repo=document_repo,
        job_repo=job_repo,
        active_job_ids=snapshot.active_job_ids,
        stale_after_seconds=settings.ingest_stale_after_seconds,
        max_attempts=MAX_ATTEMPTS,
        now=observed_at,
    )
    for candidate in stale_jobs:
        job = candidate.job
        if job.attempt_count >= MAX_ATTEMPTS:
            mutation = job_repo.update_ingest_job(
                job.id,
                status="failed",
                progress_pct=100,
                stage_progress=job.stage_progress,
                warnings=list(job.warnings),
                error_code="retry_exhausted",
                error_message_safe="Ingestion could not complete after three attempts.",
                expected_statuses=frozenset({"processing"}),
                stale_before=stale_before,
                run_token=job.run_token,
            )
            if mutation.changed:
                _audit(
                    document_repo,
                    job,
                    "exhausted",
                    {"attempt_count": job.attempt_count},
                )
            continue

        if not candidate.recoverable:
            mutation = job_repo.update_ingest_job(
                job.id,
                status="failed",
                progress_pct=100,
                stage_progress=job.stage_progress,
                warnings=list(job.warnings),
                error_code="recovery_source_unavailable",
                error_message_safe=(
                    "The source document is unavailable for ingestion recovery."
                ),
                expected_statuses=frozenset({"processing"}),
                stale_before=stale_before,
                run_token=job.run_token,
            )
            if mutation.changed:
                _audit(
                    document_repo,
                    job,
                    "unrecoverable",
                    {"reason": candidate.recovery_code},
                )
            continue

        try:
            requeue_stale_ingest_job(
                document_repo=document_repo,
                job_repo=job_repo,
                queue=queue,
                job_id=job.id,
                active_job_ids=snapshot.active_job_ids,
                stale_after_seconds=settings.ingest_stale_after_seconds,
                actor_id=None,
                audit_event_type="internal.ingest.recovered",
                max_attempts=MAX_ATTEMPTS,
                now=observed_at,
            )
        except IngestRecoveryError:
            continue
        recovered.append(job.id)
    return recovered


def _audit(
    repo: DocumentRepository,
    job: IngestJobRecord,
    event_type: str,
    payload: dict[str, object],
) -> None:
    repo.append_audit_event(
        event_type=f"internal.ingest.{event_type}",
        actor_id=None,
        target_type="ingest_job",
        target_id=job.id,
        payload={"doc_id": job.doc_id, **payload},
    )
