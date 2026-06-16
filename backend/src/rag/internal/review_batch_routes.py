"""Internal OCR review batch callbacks used by ingestion workers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..repositories.documents import DocumentRepository, get_document_repository
from ..schemas.internal import (
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
    document_repo: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ReviewBatchCreateResponse:
    _ = service
    if not payload.review_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_review_batch", "message": "Review batch must contain at least one block."},
        )
    batch = document_repo.create_review_batch(
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
    document_repo: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> ReviewBatchParsedItemsResponse:
    _ = service
    batch = document_repo.get_review_batch(batch_id)
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
    for review_item in document_repo.list_review_items_for_batch(batch.id):
        if review_item.status == "approved" and review_item.corrected_text is not None:
            for parsed in items:
                if int(parsed.get("index", -1)) == review_item.item_index:
                    parsed["text"] = review_item.corrected_text
                    flags = parsed.get("quality_flags")
                    flag_list = [str(item) for item in flags] if isinstance(flags, list) else []
                    parsed["quality_flags"] = sorted({*flag_list, "ocr_review_approved"})
                    break
    return ReviewBatchParsedItemsResponse(parsed_items=items)
