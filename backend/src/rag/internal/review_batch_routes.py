"""Internal OCR review batch callbacks used by ingestion workers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..ingestion.review_dependencies import (
    get_human_review_repository,
    get_image_review_repository,
)
from ..ingestion.review_models import (
    HumanReviewRepository,
    ImageReviewRepository,
)
from ..schemas.internal import (
    ImageReviewApprovedKeysResponse,
    ImageReviewBatchCreateRequest,
    ImageReviewBatchCreateResponse,
    ImageReviewCandidatePayload,
    ImageReviewResumeResponse,
    ReviewBatchCreateRequest,
    ReviewBatchCreateResponse,
    ReviewBatchParsedItemsResponse,
    ServiceTokenContext,
)
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-review"])


@router.post("/review-batches", response_model=ReviewBatchCreateResponse, summary="Create OCR review batch")
async def create_review_batch(
    payload: ReviewBatchCreateRequest,
    review_repo: HumanReviewRepository = Depends(get_human_review_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ReviewBatchCreateResponse:
    _ = service
    if not payload.review_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_review_batch", "message": "Review batch must contain at least one block."},
        )
    batch = review_repo.create_review_batch(
        job_id=payload.job_id,
        doc_id=payload.doc_id,
        parsed_items=payload.parsed_items,
        resume_payload=payload.resume_payload,
        review_items=[item.model_dump() for item in payload.review_items],
    )
    return ReviewBatchCreateResponse(review_batch_id=batch.id)


@router.get("/review-batches/{batch_id}/parsed-items", response_model=ReviewBatchParsedItemsResponse, summary="Read approved review batch parsed items")
async def get_review_batch_parsed_items(
    batch_id: str,
    review_repo: HumanReviewRepository = Depends(get_human_review_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ReviewBatchParsedItemsResponse:
    _ = service
    batch = review_repo.get_review_batch(batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "review_batch_not_found", "message": "Review batch was not found."},
        )
    if batch.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "review_batch_not_approved", "message": "Review batch is not approved yet."},
        )
    items = [dict(item) for item in batch.parsed_items]
    for review_item in review_repo.list_review_items_for_batch(batch.id):
        if review_item.status == "approved" and review_item.corrected_text is not None:
            for parsed in items:
                if int(parsed.get("index", -1)) == review_item.item_index:
                    parsed["text"] = review_item.corrected_text
                    flags = parsed.get("quality_flags")
                    flag_list = [str(item) for item in flags] if isinstance(flags, list) else []
                    parsed["quality_flags"] = sorted({*flag_list, "ocr_review_approved"})
                    break
    return ReviewBatchParsedItemsResponse(parsed_items=items)


@router.post("/image-review-batches", response_model=ImageReviewBatchCreateResponse, summary="Create PDF image review batch")
async def create_image_review_batch(
    payload: ImageReviewBatchCreateRequest,
    image_review_repo: ImageReviewRepository = Depends(get_image_review_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ImageReviewBatchCreateResponse:
    _ = service
    if not payload.candidates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_image_review_batch", "message": "Image review batch must contain at least one candidate."},
        )
    batch = image_review_repo.create_image_review_batch(
        job_id=payload.job_id,
        doc_id=payload.doc_id,
        parsed_items=payload.parsed_items,
        resume_payload=payload.resume_payload,
        candidates=[candidate.model_dump() for candidate in payload.candidates],
    )
    return ImageReviewBatchCreateResponse(image_review_batch_id=batch.id)


@router.get(
    "/image-review-batches/{batch_id}/approved-keys",
    response_model=ImageReviewApprovedKeysResponse,
    summary="Read approved PDF image review candidate keys",
)
async def get_image_review_approved_keys(
    batch_id: str,
    image_review_repo: ImageReviewRepository = Depends(get_image_review_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ImageReviewApprovedKeysResponse:
    _ = service
    batch = image_review_repo.get_image_review_batch(batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "image_review_batch_not_found", "message": "Image review batch was not found."},
        )
    if batch.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "image_review_batch_not_approved", "message": "Image review batch is not approved yet."},
        )
    return ImageReviewApprovedKeysResponse(
        candidate_keys=image_review_repo.get_image_review_approved_keys(batch.id)
    )


@router.get(
    "/image-review-batches/{batch_id}/resume",
    response_model=ImageReviewResumeResponse,
    summary="Read approved PDF image review candidates and parsed items",
)
async def get_image_review_resume(
    batch_id: str,
    image_review_repo: ImageReviewRepository = Depends(get_image_review_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ImageReviewResumeResponse:
    _ = service
    batch = image_review_repo.get_image_review_batch(batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "image_review_batch_not_found", "message": "Image review batch was not found."},
        )
    if batch.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "image_review_batch_not_approved", "message": "Image review batch is not approved yet."},
        )
    return ImageReviewResumeResponse(
        parsed_items=[dict(item) for item in batch.parsed_items],
        candidates=[
            _image_review_candidate_payload(candidate)
            for candidate in image_review_repo.list_image_review_candidates_for_batch(batch.id, status="approved")
        ],
        candidate_count=batch.candidate_count,
    )


def _image_review_candidate_payload(candidate) -> ImageReviewCandidatePayload:
    return ImageReviewCandidatePayload(
        candidate_key=candidate.candidate_key,
        filename=candidate.filename,
        source_kind=candidate.source_kind,
        page=candidate.page,
        bbox=candidate.bbox,
        page_area_ratio=candidate.page_area_ratio,
        object_path=candidate.object_path,
        content_type=candidate.content_type,
        width=candidate.width,
        height=candidate.height,
        content_hash=candidate.content_hash,
        quality_flags=list(candidate.quality_flags),
        score=candidate.score,
        recommended=candidate.recommended,
    )
