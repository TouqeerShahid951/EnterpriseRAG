"""Recover orphaned ingestion jobs and enforce saved worker capacity."""

from __future__ import annotations

import argparse
import time
from datetime import datetime

from rag.core.config import settings
from rag.repositories.document_models import DocumentRepository, IngestJobRecord
from rag.repositories.documents import get_document_repository
from rag.repositories.ingest_config import (
    IngestConfigRepository,
    effective_ingest_config,
    get_ingest_config_repository,
)
from rag.repositories.postgres import PostgresConnectionMixin
from rag.services.ingest_queue import IngestQueue, get_ingest_queue
from rag.services.ingest_recovery import (
    MAX_INGEST_ATTEMPTS,
    list_stale_ingest_jobs,
    requeue_stale_ingest_job,
)
from rag.services.ingest_worker_control import IngestWorkerControl, get_ingest_worker_control

ADVISORY_LOCK_ID = 867530902
MAX_ATTEMPTS = MAX_INGEST_ATTEMPTS


class _LockConnection(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Maintain ingestion worker capacity and recover stale jobs.")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.loop and not args.once:
        args.once = True
    while True:
        recovered = _run_with_lock()
        if recovered:
            print(f"recovered_ingest_jobs={','.join(recovered)}", flush=True)
        if not args.loop:
            return
        time.sleep(settings.ingest_maintenance_interval_seconds)


def _run_with_lock() -> list[str]:
    if settings.document_repository != "postgres":
        return reconcile_ingestion_jobs()
    lock = _LockConnection(settings.database_url)
    with lock._connect() as conn:
        acquired = conn.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (ADVISORY_LOCK_ID,)).fetchone()["acquired"]
        if not acquired:
            return []
        try:
            return reconcile_ingestion_jobs()
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))


def reconcile_ingestion_jobs(
    *,
    document_repo: DocumentRepository | None = None,
    queue: IngestQueue | None = None,
    control: IngestWorkerControl | None = None,
    config_repo: IngestConfigRepository | None = None,
    now: datetime | None = None,
) -> list[str]:
    document_repo = document_repo or get_document_repository()
    queue = queue or get_ingest_queue()
    control = control or get_ingest_worker_control()
    config = effective_ingest_config(repo=config_repo or get_ingest_config_repository())
    snapshot = control.apply(config.worker_concurrency)
    recovered: list[str] = []

    stale_jobs = list_stale_ingest_jobs(
        document_repo=document_repo,
        active_job_ids=snapshot.active_job_ids,
        stale_after_seconds=settings.ingest_stale_after_seconds,
        max_attempts=MAX_ATTEMPTS,
        now=now,
    )
    for candidate in stale_jobs:
        job = candidate.job
        if job.attempt_count >= MAX_ATTEMPTS:
            document_repo.update_ingest_job(
                job.id,
                status="failed",
                progress_pct=100,
                stage_progress=job.stage_progress,
                warnings=list(job.warnings),
                error_code="retry_exhausted",
                error_message_safe="Ingestion could not complete after three attempts.",
            )
            _audit(document_repo, job, "exhausted", {"attempt_count": job.attempt_count})
            continue

        if not candidate.recoverable:
            document_repo.update_ingest_job(
                job.id,
                status="failed",
                progress_pct=100,
                stage_progress=job.stage_progress,
                warnings=list(job.warnings),
                error_code="recovery_source_unavailable",
                error_message_safe="The source document is unavailable for ingestion recovery.",
            )
            _audit(document_repo, job, "unrecoverable", {"reason": candidate.recovery_code})
            continue

        requeue_stale_ingest_job(
            document_repo=document_repo,
            queue=queue,
            job_id=job.id,
            active_job_ids=snapshot.active_job_ids,
            stale_after_seconds=settings.ingest_stale_after_seconds,
            actor_id=None,
            audit_event_type="internal.ingest.recovered",
            max_attempts=MAX_ATTEMPTS,
            now=now,
        )
        recovered.append(job.id)
    return recovered


def _audit(repo: DocumentRepository, job: IngestJobRecord, event_type: str, payload: dict[str, object]) -> None:
    repo.append_audit_event(
        event_type=f"internal.ingest.{event_type}",
        actor_id=None,
        target_type="ingest_job",
        target_id=job.id,
        payload={"doc_id": job.doc_id, **payload},
    )


if __name__ == "__main__":
    main()
