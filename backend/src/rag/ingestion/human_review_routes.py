"""HTTP workflows for text/OCR human review."""

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.dependencies import require_review_user
from ..auth.identity_models import UserRecord
from ..documents.repository import DocumentRepository, get_document_repository
from ..schemas.review import (
    ReviewApproveRequest,
    ReviewDecisionResponse,
    ReviewQueueResponse,
)
from .contracts import IngestJobPayload
from .job_dependencies import get_ingest_job_repository
from .job_models import IngestJobRepository
from .queue import IngestQueue, get_ingest_queue
from .review_access import (
    can_review_document,
    require_visible_approvable_review_item,
    require_visible_pending_review_item,
)
from .review_dependencies import get_human_review_repository
from .review_models import HumanReviewRepository
from .review_presenters import review_item_response

router = APIRouter()


@router.get("", response_model=ReviewQueueResponse, summary="List human review items")
async def list_review_queue(
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    review_repo: HumanReviewRepository = Depends(get_human_review_repository),
) -> ReviewQueueResponse:
    items = [
        review_item_response(item)
        for item in review_repo.list_review_items(status="pending")
        if can_review_document(user, document_repo, item.doc_id)
    ]
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
    review_repo: HumanReviewRepository = Depends(get_human_review_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> ReviewDecisionResponse:
    review_item = require_visible_approvable_review_item(
        user,
        document_repo,
        review_repo,
        item_id,
    )
    decision = review_repo.approve_review_item(
        item_id, corrected_text=payload.corrected_text, reviewer_id=user.id
    )
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "review_item_not_found",
                "message": "Review item was not found.",
            },
        )
    resume_claimed = False
    if decision.batch_complete:
        job = job_repo.get_ingest_job(decision.batch.job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ingest_job_not_found",
                    "message": "The ingestion job for this review batch was not found.",
                },
            )
        if job.status == "cancelled":
            document_repo.append_audit_event(
                event_type="review.resume_skipped",
                actor_id=user.id,
                target_type="review_item",
                target_id=decision.item.id,
                payload={
                    "batch_id": decision.batch.id,
                    "doc_id": decision.batch.doc_id,
                    "reason": "ingest_cancelled",
                },
            )
            return ReviewDecisionResponse(
                id=decision.item.id,
                status="approved",
                batch_id=decision.batch.id,
                batch_status="approved",
                batch_complete=decision.batch_complete,
            )
        resume_payload = dict(decision.batch.resume_payload)
        resume_payload["review_batch_id"] = decision.batch.id
        claimed = job_repo.update_ingest_job(
            decision.batch.job_id,
            status="queued",
            progress_pct=0,
            expected_statuses=frozenset({"human_review"}),
        )
        resume_claimed = claimed.changed
        if resume_claimed:
            try:
                queue.enqueue(IngestJobPayload.from_dict(resume_payload))
            except RuntimeError as exc:
                job_repo.update_ingest_job(
                    decision.batch.job_id,
                    status="human_review",
                    progress_pct=35,
                    expected_statuses=frozenset({"queued"}),
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "queue_unavailable",
                        "message": "Upload queue is unavailable.",
                    },
                ) from exc
    if review_item.status == "pending" or resume_claimed:
        document_repo.append_audit_event(
            event_type="review.approved",
            actor_id=user.id,
            target_type="review_item",
            target_id=decision.item.id,
            payload={
                "batch_id": decision.batch.id,
                "doc_id": decision.batch.doc_id,
                "batch_complete": decision.batch_complete,
            },
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
    review_repo: HumanReviewRepository = Depends(get_human_review_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> ReviewDecisionResponse:
    require_visible_pending_review_item(user, document_repo, review_repo, item_id)
    decision = review_repo.reject_review_item(item_id, reviewer_id=user.id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "review_item_not_found",
                "message": "Review item was not found.",
            },
        )
    job_repo.update_ingest_job(
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
