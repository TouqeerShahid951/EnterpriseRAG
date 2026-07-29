"""Internal ingestion callbacks used by the worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.config import settings
from ..documents.repository import DocumentRepository, get_document_repository
from ..ingestion.job_dependencies import get_ingest_job_repository
from ..ingestion.job_models import IngestJobRecord, IngestJobRepository
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.delivery.service import IngestDeliveryService
from rag.ingestion.publication.dependencies import publication_repository_for
from rag.ingestion.internal_schemas import (
    InternalJobAttemptRequest,
    InternalJobAttemptResponse,
    InternalJobEventRequest,
    InternalJobFailureRequest,
    InternalJobFailureResponse,
    InternalJobLeaseRequest,
    InternalJobStatusResponse,
    InternalJobStatusRequest,
    InternalParserProvenanceRequest,
)
from rag.internal.schemas import InternalMutationResponse
from rag.shared.persistence import PostgresConnectionMixin
from ..documents.upload.status import progress_for_status_update
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-ingest"], dependencies=[Depends(require_service_token)])
TERMINAL_STATUSES = {"complete", "failed", "human_review", "cancelled"}
MAX_INGEST_ATTEMPTS = 3


@router.get(
    "/ingest/jobs/{job_id}/status",
    response_model=InternalJobStatusResponse,
    summary="Read ingestion job status from the worker",
)
async def get_ingest_job_status(
    job_id: str,
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> InternalJobStatusResponse:
    job = job_repo.get_ingest_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
        )
    return InternalJobStatusResponse(job_id=job.id, doc_id=job.doc_id, status=job.status)  # type: ignore[arg-type]


@router.post(
    "/ingest/jobs/{job_id}/status",
    response_model=InternalMutationResponse,
    summary="Update ingestion job status from the worker",
)
async def update_ingest_job_status(
    job_id: str,
    payload: InternalJobStatusRequest,
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> InternalMutationResponse:
    current_job = job_repo.get_ingest_job(job_id)
    if current_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
        )
    if current_job.status in TERMINAL_STATUSES:
        return InternalMutationResponse()
    _raise_if_lease_lost(
        current_job,
        payload.run_token,
        next_status=payload.status,
    )
    progress_pct = progress_for_status_update(
        current_job,
        next_status=payload.status,
        next_progress_pct=payload.progress_pct,
    )
    stage_progress = payload.stage_progress.model_dump() if payload.stage_progress else None
    if payload.status == "failed" and stage_progress is None:
        stage_progress = current_job.stage_progress
    warnings = payload.warnings if payload.warnings is not None else list(current_job.warnings)
    mutation = job_repo.update_ingest_job(
        job_id,
        status=payload.status,
        progress_pct=progress_pct,
        stage_progress=stage_progress,
        warnings=warnings,
        error_code=payload.error_code,
        error_message_safe=payload.error_message_safe,
        expected_statuses=frozenset({current_job.status}),
        run_token=payload.run_token,
    )
    if mutation.job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
        )
    if not mutation.changed:
        if mutation.job is not None:
            _raise_if_lease_lost(
                mutation.job,
                payload.run_token,
                next_status=payload.status,
            )
        return InternalMutationResponse()
    job = mutation.job

    if payload.status in TERMINAL_STATUSES:
        document_repo.append_audit_event(
            event_type="internal.ingest.status",
            actor_id=None,
            target_type="ingest_job",
            target_id=job.id,
            payload={
                "doc_id": job.doc_id,
                "status": payload.status,
                "progress_pct": progress_pct,
                "error_code": payload.error_code,
            },
        )
    return InternalMutationResponse()


@router.post(
    "/ingest/jobs/{job_id}/attempt",
    response_model=InternalJobAttemptResponse,
    summary="Atomically start an ingestion execution attempt",
)
async def start_ingest_job_attempt(
    job_id: str,
    payload: InternalJobAttemptRequest,
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> InternalJobAttemptResponse:
    if payload.delivery_id:
        if payload.run_token is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "ingest_run_token_required",
                    "message": "A delivery claim requires a run token.",
                },
            )
        claim = IngestDeliveryService(job_repo).claim_worker_delivery(
            job_id,
            delivery_id=payload.delivery_id,
            run_token=payload.run_token,
            max_failures=MAX_INGEST_ATTEMPTS,
        )
        job = claim.job
        disposition = claim.disposition
        claimed = claim.claimed
    else:
        attempt = job_repo.start_ingest_attempt(
            job_id,
            max_attempts=MAX_INGEST_ATTEMPTS,
            stale_after_seconds=settings.ingest_stale_after_seconds,
            run_token=payload.run_token,
        )
        job = attempt.job
        claimed = attempt.claimed
        disposition = "accepted" if claimed else (
            "duplicate" if job is not None and job.active_delivery_id is not None else (
                "busy" if job is not None and job.status == "processing" else "exhausted"
            )
        )
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    return InternalJobAttemptResponse(
        status=disposition,
        attempt_count=job.attempt_count,
        failure_attempt_count=job.failure_attempt_count,
        max_attempts=MAX_INGEST_ATTEMPTS,
        job_status=job.status,
        run_token=job.run_token if claimed else None,
    )


@router.post(
    "/ingest/jobs/{job_id}/failure",
    response_model=InternalJobFailureResponse,
    summary="Record one token-fenced ingestion worker failure",
)
async def record_ingest_job_failure(
    job_id: str,
    payload: InternalJobFailureRequest,
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> InternalJobFailureResponse:
    current = job_repo.get_ingest_job(job_id)
    if current is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
        )
    try:
        retry_message = (
            IngestJobPayload.from_dict(payload.retry_message)
            if payload.retry_message is not None
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_ingest_retry_message",
                "message": str(exc),
            },
        ) from exc
    if retry_message is not None and (
        retry_message.job_id != job_id or retry_message.doc_id != current.doc_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_ingest_retry_message",
                "message": "Retry message does not match the ingestion job.",
            },
        )
    retry_at = datetime.now(UTC) + timedelta(
        seconds=30 * (2 ** min(current.failure_attempt_count, 4))
    )
    mutation = IngestDeliveryService(job_repo).record_worker_failure(
        job_id,
        run_token=payload.run_token,
        max_failures=MAX_INGEST_ATTEMPTS,
        error_code=payload.error_code,
        error_message_safe=payload.error_message_safe,
        retry_message=retry_message,
        available_at=retry_at,
    )
    job = mutation.job
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
        )
    if not mutation.changed and job.last_failure_run_token != payload.run_token:
        _raise_if_lease_lost(job, payload.run_token, next_status=job.status)
    if mutation.changed and job.status == "failed":
        if settings.document_repository == "postgres" and isinstance(
            document_repo, PostgresConnectionMixin
        ):
            publication_repository_for(settings).cancel_building(job_id=job.id)
        document_repo.append_audit_event(
            event_type="internal.ingest.status",
            actor_id=None,
            target_type="ingest_job",
            target_id=job.id,
            payload={
                "doc_id": job.doc_id,
                "status": job.status,
                "progress_pct": job.progress_pct,
                "error_code": payload.error_code,
                "failure_attempt_count": job.failure_attempt_count,
            },
        )
    return InternalJobFailureResponse(
        status=job.status,
        failure_attempt_count=job.failure_attempt_count,
        retry_scheduled=job.status == "queued" and not mutation.exhausted,
        changed=mutation.changed,
    )


@router.post(
    "/ingest/jobs/{job_id}/heartbeat",
    response_model=InternalMutationResponse,
    summary="Refresh an ingestion job heartbeat",
)
async def heartbeat_ingest_job(
    job_id: str,
    payload: InternalJobLeaseRequest,
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> InternalMutationResponse:
    heartbeat = job_repo.heartbeat_ingest_job(job_id, run_token=payload.run_token)
    if heartbeat.job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    if not heartbeat.changed and heartbeat.job.status == "processing":
        _raise_if_lease_lost(heartbeat.job, payload.run_token, next_status=heartbeat.job.status)
    return InternalMutationResponse()


@router.post(
    "/ingest/jobs/{job_id}/events",
    response_model=InternalMutationResponse,
    summary="Append an ingestion operational audit event",
)
async def append_ingest_job_event(
    job_id: str,
    payload: InternalJobEventRequest,
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> InternalMutationResponse:
    job = job_repo.get_ingest_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    document_repo.append_audit_event(
        event_type=f"internal.ingest.{payload.event_type}",
        actor_id=None,
        target_type="ingest_job",
        target_id=job.id,
        payload={"doc_id": job.doc_id, **payload.payload},
    )
    return InternalMutationResponse()


@router.post(
    "/ingest/jobs/{job_id}/parser-provenance",
    response_model=InternalMutationResponse,
    summary="Persist parser provenance and append an audit event",
)
async def record_ingest_parser_provenance(
    job_id: str,
    payload: InternalParserProvenanceRequest,
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> InternalMutationResponse:
    current_job = job_repo.get_ingest_job(job_id)
    if current_job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    _raise_if_lease_lost(current_job, payload.run_token, next_status=current_job.status)
    job = job_repo.record_ingest_parser_provenance(
        job_id,
        provenance=payload.provenance,
        run_token=payload.run_token,
    )
    if job is None:
        latest = job_repo.get_ingest_job(job_id)
        if latest is not None:
            _raise_if_lease_lost(latest, payload.run_token, next_status=latest.status)
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    return InternalMutationResponse()


def _raise_if_lease_lost(
    job: IngestJobRecord,
    run_token: str | None,
    *,
    next_status: str,
) -> None:
    if run_token is None:
        if job.run_token is None:
            return
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ingest_job_lease_lost",
                "message": "Ingestion job execution lease is no longer valid.",
            },
        )
    if job.run_token == run_token:
        return
    if job.run_token is None and job.status == "queued" and next_status == "processing":
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ingest_job_lease_lost",
            "message": "Ingestion job execution lease is no longer valid.",
        },
    )
