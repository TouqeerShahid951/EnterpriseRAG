"""Thin service-token transport for worker checkpoint references."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from rag.internal.service_token_auth import require_service_token

from .dependencies import get_checkpoint_service
from .models import CheckpointDescriptor, CheckpointLeaseLost
from .schemas import CheckpointCommitRequest, CheckpointListResponse, CheckpointResponse
from .service import CheckpointService


router = APIRouter(tags=["internal-ingest-checkpoints"], dependencies=[Depends(require_service_token)])


@router.post("/ingest/jobs/{job_id}/checkpoints", response_model=CheckpointResponse)
async def commit_checkpoint(
    job_id: str,
    payload: CheckpointCommitRequest,
    service: CheckpointService = Depends(get_checkpoint_service),
) -> CheckpointResponse:
    if payload.document_id == "":
        raise HTTPException(status_code=422, detail={"code": "document_id_required", "message": "Document id is required."})
    descriptor = CheckpointDescriptor(
        job_id=job_id,
        document_id=payload.document_id,
        stage_key=payload.stage_key,
        object_key=payload.object_key,
        schema_version=payload.schema_version,
        body_sha256=payload.body_sha256,
        compressed_size=payload.compressed_size,
        decoded_size=payload.decoded_size,
        upstream_sha256=payload.upstream_sha256,
        configuration_digest=payload.configuration_digest,
        range_start=payload.range_start,
        range_end=payload.range_end,
        model_identity=payload.model_identity,
        vector_dimension=payload.vector_dimension,
    )
    _validate_generated_key(descriptor)
    try:
        result = service.repository.commit(descriptor, run_token=payload.run_token)
    except CheckpointLeaseLost as exc:
        raise HTTPException(status_code=409, detail={"code": "ingest_job_lease_lost", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "checkpoint_conflict", "message": str(exc)}) from exc
    return _response(result)


@router.delete("/ingest/jobs/{job_id}/checkpoints")
async def invalidate_checkpoint(
    job_id: str,
    payload: CheckpointCommitRequest,
    service: CheckpointService = Depends(get_checkpoint_service),
) -> dict[str, bool]:
    descriptor = CheckpointDescriptor(job_id=job_id, **payload.model_dump(exclude={"run_token"}))
    _validate_generated_key(descriptor)
    try:
        return {"invalidated": service.repository.invalidate(descriptor, run_token=payload.run_token)}
    except CheckpointLeaseLost as exc:
        raise HTTPException(status_code=409, detail={"code": "ingest_job_lease_lost", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "checkpoint_conflict", "message": str(exc)}) from exc


@router.get("/ingest/jobs/{job_id}/checkpoints", response_model=CheckpointListResponse)
async def list_checkpoints(
    job_id: str,
    stage_prefix: str = Query(default="", max_length=200),
    service: CheckpointService = Depends(get_checkpoint_service),
) -> CheckpointListResponse:
    return CheckpointListResponse(checkpoints=[_response(item) for item in service.repository.list(job_id=job_id, stage_prefix=stage_prefix)])


@router.get("/ingest/jobs/{job_id}/checkpoints/{stage_key:path}", response_model=CheckpointResponse)
async def get_checkpoint(
    job_id: str,
    stage_key: str,
    service: CheckpointService = Depends(get_checkpoint_service),
) -> CheckpointResponse:
    result = service.repository.get(job_id=job_id, stage_key=stage_key)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "checkpoint_not_found", "message": "Checkpoint was not found."})
    return _response(result)


def _validate_generated_key(descriptor: CheckpointDescriptor) -> None:
    prefix = f"ingest-checkpoints/{descriptor.document_id}/{descriptor.job_id}/"
    if not descriptor.object_key.startswith(prefix) or ".." in descriptor.object_key:
        raise HTTPException(status_code=422, detail={"code": "invalid_checkpoint_key", "message": "Checkpoint object key is invalid."})


def _response(descriptor: CheckpointDescriptor) -> CheckpointResponse:
    return CheckpointResponse(**descriptor.__dict__)
