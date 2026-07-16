"""Recover stale ingestion jobs and enforce saved worker capacity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from rag.core.config import settings
from rag.documents.models import DocumentRepository
from rag.documents.repository import get_document_repository
from rag.ingestion.configuration import IngestConfigRepository
from rag.ingestion.configuration.dependencies import (
    effective_ingest_config,
    get_ingest_config_repository,
)
from rag.ingestion.job_dependencies import ingest_job_repository_for
from rag.ingestion.job_models import IngestJobRecord, IngestJobRepository
from rag.shared.persistence import PostgresConnectionMixin

from .adapters.http import ServiceRequestError
from .delivery.service import IngestDeliveryService, dispatch_pending_deliveries
from .indexing.qdrant import QdrantClient
from .publication.dependencies import publication_service_for
from .publication.service import IndexPublicationService
from .queue import IngestQueue, get_ingest_queue
from .recovery import (
    IngestRecoveryError,
    MAX_INGEST_ATTEMPTS,
    list_stale_ingest_jobs,
    requeue_stale_ingest_job,
)
from .worker_control import IngestWorkerControl, get_ingest_worker_control


MAX_ATTEMPTS = MAX_INGEST_ATTEMPTS
logger = logging.getLogger(__name__)


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
    delivery = IngestDeliveryService(job_repo)
    _dispatch_best_effort(delivery, queue)
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
        if job.failure_attempt_count >= MAX_ATTEMPTS:
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
                _retire_failed_generation(document_repo, job.id)
                _audit(
                    document_repo,
                    job,
                    "exhausted",
                    {
                        "attempt_count": job.attempt_count,
                        "failure_attempt_count": job.failure_attempt_count,
                    },
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
                _retire_failed_generation(document_repo, job.id)
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


def _dispatch_best_effort(
    delivery: IngestDeliveryService,
    queue: IngestQueue,
) -> None:
    try:
        dispatch_pending_deliveries(delivery, queue)
    except Exception:
        logger.warning("ingestion outbox maintenance deferred")


def _retire_failed_generation(document_repo: DocumentRepository, job_id: str) -> None:
    if settings.document_repository == "postgres" and isinstance(
        document_repo, PostgresConnectionMixin
    ):
        publication_service_for(settings).cancel_building(job_id=job_id)


def retire_index_generations(
    *,
    publication: IndexPublicationService | None = None,
    qdrant: QdrantClient | None = None,
) -> int:
    """Delete index generations that have already been replaced in PostgreSQL."""
    if publication is None and settings.document_repository != "postgres":
        return 0
    publication = publication or publication_service_for(settings)
    generations = publication.list_retiring(limit=20)
    if not generations:
        return 0
    qdrant = qdrant or QdrantClient(
        base_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        timeout_seconds=settings.rag_http_timeout_seconds,
    )
    retired = 0
    for generation in generations:
        try:
            qdrant.delete_generation_points(generation.id)
        except ServiceRequestError as exc:
            logger.warning(
                "index generation retirement deferred generation_id=%s service=%s",
                generation.id,
                exc.service,
            )
            continue
        if publication.mark_retired(generation.id):
            retired += 1
    return retired
