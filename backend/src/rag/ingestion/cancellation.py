"""Application workflow for cancelling an active ingestion job."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..auth.document_access import can_manage_document_ingestion
from ..auth.identity_models import UserRecord
from ..documents.models import DocumentRepository
from .job_models import IngestJobRepository
from .queue import IngestQueue


CANCELLABLE_JOB_STATUSES = frozenset(
    {"scheduled", "queued", "processing", "human_review"}
)
CancellationErrorCategory = Literal["not_found", "forbidden"]


class BuildingGenerationCleaner(Protocol):
    def delete_building_vectors(self, job_id: str) -> None: ...


class DocumentVectorCleanupError(RuntimeError):
    """A safe, diagnostic vector-cleanup failure."""


class IngestCancellationError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        category: CancellationErrorCategory,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.category = category


@dataclass(frozen=True)
class CancelIngestJobResult:
    job_id: str
    status: str
    message: str


class CancelIngestJob:
    def __init__(
        self,
        *,
        document_repo: DocumentRepository,
        job_repo: IngestJobRepository,
        queue: IngestQueue,
        vector_cleaner: BuildingGenerationCleaner,
    ) -> None:
        self._document_repo = document_repo
        self._job_repo = job_repo
        self._queue = queue
        self._vector_cleaner = vector_cleaner

    def execute(self, *, job_id: str, actor: UserRecord) -> CancelIngestJobResult:
        job = self._job_repo.get_ingest_job(job_id)
        if job is None:
            raise IngestCancellationError(
                code="job_not_found",
                message="Ingestion job was not found.",
                category="not_found",
            )

        document = self._document_repo.get_document(
            job.doc_id,
            include_deleted=True,
        )
        if document is None:
            raise IngestCancellationError(
                code="document_not_found",
                message="Ingested document was not found.",
                category="not_found",
            )
        if not can_manage_document_ingestion(actor, document):
            raise IngestCancellationError(
                code="ingest_cancel_forbidden",
                message=(
                    "Only the uploader or a scoped admin can cancel this ingestion job."
                ),
                category="forbidden",
            )
        if job.status not in CANCELLABLE_JOB_STATUSES:
            return _already_finished(job.id, job.status)

        cancellation = self._job_repo.cancel_ingest_job(
            job.id,
            allowed_statuses=CANCELLABLE_JOB_STATUSES,
        )
        if cancellation.job is None:
            raise IngestCancellationError(
                code="job_not_found",
                message="Ingestion job was not found.",
                category="not_found",
            )
        if not cancellation.changed:
            return _already_finished(cancellation.job.id, cancellation.job.status)

        revoke_error = _revoke_queued_task(self._queue, job.id)
        vector_cleanup_error = _delete_building_vectors(
            self._vector_cleaner,
            job.id,
        )
        self._document_repo.append_audit_event(
            event_type="ingest.cancelled",
            actor_id=actor.id,
            target_type="ingest_job",
            target_id=job.id,
            payload={
                "doc_id": document.id,
                "status_before": job.status,
                "progress_pct": job.progress_pct,
                "review_items_closed": cancellation.review_items_closed,
                "revoke_error": revoke_error,
                "vector_cleanup_error": vector_cleanup_error,
            },
        )
        return CancelIngestJobResult(
            job_id=cancellation.job.id,
            status="cancelled",
            message="Ingestion job cancelled.",
        )


def _already_finished(job_id: str, status: str) -> CancelIngestJobResult:
    return CancelIngestJobResult(
        job_id=job_id,
        status=status,
        message=f"Job is already {status}.",
    )


def _revoke_queued_task(queue: IngestQueue, job_id: str) -> str | None:
    cancel = getattr(queue, "cancel", None)
    if not callable(cancel):
        return "queue_cancel_unavailable"
    try:
        cancel(job_id)
    except RuntimeError as exc:
        return str(exc)[:300]
    return None


def _delete_building_vectors(
    cleaner: BuildingGenerationCleaner,
    job_id: str,
) -> str | None:
    try:
        cleaner.delete_building_vectors(job_id)
    except DocumentVectorCleanupError as exc:
        return str(exc)[:300]
    return None
