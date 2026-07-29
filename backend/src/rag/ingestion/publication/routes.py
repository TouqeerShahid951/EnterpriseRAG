"""Thin service-token transport for index generation publication."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from rag.internal.service_token_auth import require_service_token

from .dependencies import get_index_publication_repository
from .models import IndexGeneration
from .repository import IndexPublicationRepository
from .schemas import (
    IndexGenerationCancelResponse,
    IndexGenerationResponse,
    IndexGenerationStageRequest,
    IndexGenerationTransitionRequest,
)


router = APIRouter(
    tags=["internal-ingest-publication"],
    dependencies=[Depends(require_service_token)],
)


@router.post(
    "/ingest/jobs/{job_id}/index-generation",
    response_model=IndexGenerationResponse,
    summary="Stage one isolated document index generation",
)
async def stage_index_generation(
    job_id: str,
    payload: IndexGenerationStageRequest,
    repository: IndexPublicationRepository = Depends(get_index_publication_repository),
) -> IndexGenerationResponse:
    try:
        generation = repository.stage(
            generation_id=payload.generation_id,
            job_id=job_id,
            run_token=payload.run_token,
            input_hash=payload.input_hash,
            configuration_digest=payload.configuration_digest,
            expected_point_count=payload.expected_point_count,
            expected_item_hash=payload.expected_item_hash,
            vector_dimension=payload.vector_dimension,
            staged_metadata={
                "metadata": payload.metadata,
                "claims": [claim.model_dump() for claim in payload.claims],
                "supersedes": payload.supersedes,
                "warnings": payload.warnings,
                "abbreviation_entries": [
                    entry.model_dump() for entry in payload.abbreviation_entries
                ],
            },
        )
    except ValueError as exc:
        raise _publication_conflict(exc) from exc
    return _response(generation)


@router.post(
    "/ingest/jobs/{job_id}/index-generation/verified",
    response_model=IndexGenerationResponse,
    summary="Record verified Qdrant generation contents",
)
async def verify_index_generation(
    job_id: str,
    payload: IndexGenerationTransitionRequest,
    repository: IndexPublicationRepository = Depends(get_index_publication_repository),
) -> IndexGenerationResponse:
    try:
        generation = repository.mark_verified(
            generation_id=payload.generation_id,
            job_id=job_id,
            run_token=payload.run_token,
        )
    except ValueError as exc:
        raise _publication_conflict(exc) from exc
    return _response(generation)


@router.post(
    "/ingest/jobs/{job_id}/index-generation/activate",
    response_model=IndexGenerationResponse,
    summary="Atomically activate one verified document index generation",
)
async def activate_index_generation(
    job_id: str,
    payload: IndexGenerationTransitionRequest,
    repository: IndexPublicationRepository = Depends(get_index_publication_repository),
) -> IndexGenerationResponse:
    try:
        generation = repository.activate(
            generation_id=payload.generation_id,
            job_id=job_id,
            run_token=payload.run_token,
        )
    except ValueError as exc:
        raise _publication_conflict(exc) from exc
    return _response(generation)


@router.post(
    "/ingest/jobs/{job_id}/index-generation/cancel",
    response_model=IndexGenerationCancelResponse,
    summary="Discard only an unfinished document index generation",
)
async def cancel_index_generation(
    job_id: str,
    repository: IndexPublicationRepository = Depends(get_index_publication_repository),
) -> IndexGenerationCancelResponse:
    return IndexGenerationCancelResponse(
        generation_id=repository.cancel_building(job_id=job_id)
    )


def _response(generation: IndexGeneration) -> IndexGenerationResponse:
    return IndexGenerationResponse(
        generation_id=generation.id,
        state=generation.state,  # type: ignore[arg-type]
        expected_point_count=generation.expected_point_count,
        expected_item_hash=generation.expected_item_hash,
        vector_dimension=generation.vector_dimension,
    )


def _publication_conflict(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "index_generation_conflict", "message": str(exc)},
    )
