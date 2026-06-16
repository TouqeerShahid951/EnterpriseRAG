from fastapi import APIRouter, Depends, HTTPException, status

from ...auth.dependencies import require_review_user
from ...repositories.document_models import ReviewItemRecord
from ...repositories.documents import DocumentRepository, get_document_repository
from ...repositories.identity import UserRecord
from ...schemas.review import ReviewApproveRequest, ReviewDecisionResponse, ReviewItem, ReviewQueueResponse
from ...services.ingest_queue import IngestQueue, IngestQueueMessage, get_ingest_queue

router = APIRouter(prefix="/review-queue", tags=["review-queue"])


@router.get("", response_model=ReviewQueueResponse, summary="List human review items")
async def list_review_queue(
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> ReviewQueueResponse:
    _ = user
    items = [_review_item_response(item) for item in document_repo.list_review_items(status="pending")]
    return ReviewQueueResponse(items=items, total=len(items))


@router.post(
    "/{item_id}/approve",
    responses={
        status.HTTP_200_OK: {"model": ReviewDecisionResponse},
    },
    summary="Approve OCR correction and resume ingestion",
)
async def approve_review_item(
    item_id: str,
    payload: ReviewApproveRequest,
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> ReviewDecisionResponse:
    decision = document_repo.approve_review_item(item_id, corrected_text=payload.corrected_text, reviewer_id=user.id)
    if decision is None:
        raise HTTPException(status_code=404, detail={"code": "review_item_not_found", "message": "Review item was not found."})
    if decision.batch_complete:
        resume_payload = dict(decision.batch.resume_payload)
        resume_payload["review_batch_id"] = decision.batch.id
        try:
            queue.enqueue(IngestQueueMessage.from_payload(resume_payload))
            document_repo.update_ingest_job(decision.batch.job_id, status="queued", progress_pct=0)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Upload queue is unavailable."}) from exc
    document_repo.append_audit_event(
        event_type="review.approved",
        actor_id=user.id,
        target_type="review_item",
        target_id=decision.item.id,
        payload={"batch_id": decision.batch.id, "doc_id": decision.batch.doc_id, "batch_complete": decision.batch_complete},
    )
    return ReviewDecisionResponse(
        id=decision.item.id,
        status="approved",
        batch_id=decision.batch.id,
        batch_status="approved" if decision.batch_complete else "pending",
        batch_complete=decision.batch_complete,
    )


@router.post(
    "/{item_id}/reject",
    responses={
        status.HTTP_200_OK: {"model": ReviewDecisionResponse},
    },
    summary="Reject a human review item",
)
async def reject_review_item(
    item_id: str,
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> ReviewDecisionResponse:
    decision = document_repo.reject_review_item(item_id, reviewer_id=user.id)
    if decision is None:
        raise HTTPException(status_code=404, detail={"code": "review_item_not_found", "message": "Review item was not found."})
    document_repo.update_ingest_job(
        decision.batch.job_id,
        status="failed",
        progress_pct=35,
        error_code="ocr_review_rejected",
        error_message_safe="OCR review was rejected before indexing.",
    )
    document_repo.append_audit_event(
        event_type="review.rejected",
        actor_id=user.id,
        target_type="review_item",
        target_id=decision.item.id,
        payload={"batch_id": decision.batch.id, "doc_id": decision.batch.doc_id},
    )
    return ReviewDecisionResponse(
        id=decision.item.id,
        status="rejected",
        batch_id=decision.batch.id,
        batch_status="rejected",
        batch_complete=False,
    )


def _review_item_response(item: ReviewItemRecord) -> ReviewItem:
    return ReviewItem(
        id=item.id,
        batch_id=item.batch_id,
        doc_id=item.doc_id,
        doc_title=item.doc_title,
        item_index=item.item_index,
        item_type=item.item_type,
        page_start=item.page_start,
        page_end=item.page_end,
        bbox=item.bbox,
        quality_flags=list(item.quality_flags),
        confidence=item.confidence,
        partial_text=item.partial_text,
        corrected_text=item.corrected_text,
        status=item.status,  # type: ignore[arg-type]
        assigned_to=item.assigned_to,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
