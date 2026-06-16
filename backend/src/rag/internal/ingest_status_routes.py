"""Internal ingestion callbacks used by the worker."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.config import settings
from ..repositories.documents import DocumentRepository, get_document_repository
from ..schemas.internal import (
    InternalJobAttemptResponse,
    InternalJobEventRequest,
    InternalJobStatusRequest,
    InternalParserProvenanceRequest,
    InternalMutationResponse,
    ServiceTokenContext,
)
from ..services.upload_status import progress_for_status_update
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-ingest"])
TERMINAL_STATUSES = {"complete", "failed", "human_review"}
MAX_INGEST_ATTEMPTS = 3


@router.post(
    "/ingest/jobs/{job_id}/status",
    response_model=InternalMutationResponse,
    summary="Update ingestion job status from the worker",
)
async def update_ingest_job_status(
    job_id: str,
    payload: InternalJobStatusRequest,
    document_repo: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
    current_job = document_repo.get_ingest_job(job_id)
    if current_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
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
    job = document_repo.update_ingest_job(
        job_id,
        status=payload.status,
        progress_pct=progress_pct,
        stage_progress=stage_progress,
        warnings=warnings,
        error_code=payload.error_code,
        error_message_safe=payload.error_message_safe,
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
        )

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
    document_repo: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalJobAttemptResponse:
    _ = service
    current = document_repo.get_ingest_job(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    job = document_repo.start_ingest_attempt(
        job_id,
        max_attempts=MAX_INGEST_ATTEMPTS,
        stale_after_seconds=settings.ingest_stale_after_seconds,
    )
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    accepted = job.attempt_count > current.attempt_count
    disposition = "accepted" if accepted else (
        "busy" if job.status == "processing" and job.attempt_count < MAX_INGEST_ATTEMPTS else "exhausted"
    )
    return InternalJobAttemptResponse(
        status=disposition,
        attempt_count=job.attempt_count,
        max_attempts=MAX_INGEST_ATTEMPTS,
        job_status=job.status,
    )


@router.post(
    "/ingest/jobs/{job_id}/heartbeat",
    response_model=InternalMutationResponse,
    summary="Refresh an ingestion job heartbeat",
)
async def heartbeat_ingest_job(
    job_id: str,
    document_repo: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
    if document_repo.heartbeat_ingest_job(job_id) is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
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
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
    job = document_repo.get_ingest_job(job_id)
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
    document_repo: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
    job = document_repo.record_ingest_parser_provenance(job_id, provenance=payload.provenance)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Ingestion job was not found."})
    return InternalMutationResponse()
