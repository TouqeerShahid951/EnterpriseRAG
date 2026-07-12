"""Internal ingestion callbacks used by the worker."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.config import settings
from ..repositories.documents import DocumentRepository, get_document_repository
from ..repositories.ingest_job_models import IngestJobRecord, IngestJobRepository
from ..repositories.ingest_jobs import get_ingest_job_repository
from ..schemas.internal import (
    InternalJobAttemptRequest,
    InternalJobAttemptResponse,
    InternalJobEventRequest,
    InternalJobLeaseRequest,
    InternalJobStatusResponse,
    InternalJobStatusRequest,
    InternalParserProvenanceRequest,
    InternalMutationResponse,
    ServiceTokenContext,
)
from ..services.upload_status import progress_for_status_update
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-ingest"])
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
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalJobStatusResponse:
    _ = service
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
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
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
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalJobAttemptResponse:
    _ = service
    attempt = job_repo.start_ingest_attempt(
        job_id,
        max_attempts=MAX_INGEST_ATTEMPTS,
        stale_after_seconds=settings.ingest_stale_after_seconds,
        run_token=payload.run_token,
    )
    if attempt.job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    job = attempt.job
    disposition = "accepted" if attempt.claimed else (
        "busy" if job.status == "processing" else "exhausted"
    )
    return InternalJobAttemptResponse(
        status=disposition,
        attempt_count=job.attempt_count,
        max_attempts=MAX_INGEST_ATTEMPTS,
        job_status=job.status,
        run_token=job.run_token if attempt.claimed else None,
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
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
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
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
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
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
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
