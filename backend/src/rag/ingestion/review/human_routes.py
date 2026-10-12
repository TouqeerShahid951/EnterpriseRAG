"""HTTP workflows for text/OCR human review."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from rag.auth.dependencies import require_review_user
from rag.auth.identity_models import UserRecord
from rag.documents.repository import DocumentRepository, get_document_repository
from rag.ingestion.review.schemas import (
    ReviewApproveRequest,
    ReviewDecisionResponse,
    ReviewQueueResponse,
)
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.parsers.images.analysis import image_item_description
from rag.ingestion.parsers.models import parsed_item_from_dict
from rag.ingestion.delivery.service import (
    IngestDeliveryService,
    dispatch_pending_deliveries,
)
from rag.ingestion.job_dependencies import get_ingest_job_repository
from rag.ingestion.job_models import IngestJobRepository
from rag.ingestion.queue import IngestQueue, get_ingest_queue
from .access import (
    can_review_document,
    require_visible_approvable_review_item,
    require_visible_pending_review_item,
)
from .dependencies import get_human_review_repository
from .models import HumanReviewRepository
from .presenters import review_item_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=ReviewQueueResponse, summary="List human review items")
async def list_review_queue(
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    review_repo: HumanReviewRepository = Depends(get_human_review_repository),
) -> ReviewQueueResponse:
    visible_items = [
        item
        for item in review_repo.list_review_items(status="pending")
        if can_review_document(user, document_repo, item.doc_id)
    ]
    assets_by_document = {
        item.doc_id: document_repo.list_document_image_assets(item.doc_id)
        for item in visible_items
    }
    parsed_items_by_batch = {
        batch_id: {
            str(parsed_item.get("index")): parsed_item
            for parsed_item in batch.parsed_items
            if isinstance(parsed_item, dict)
        }
        for batch_id in {item.batch_id for item in visible_items}
        if (batch := review_repo.get_review_batch(batch_id)) is not None
    }
    items = []
    for item in visible_items:
        parsed_item = parsed_items_by_batch.get(item.batch_id, {}).get(
            str(item.item_index)
        )
        image_asset_id = parsed_item.get("image_asset_id") if parsed_item else None
        image_asset = next(
            (
                asset
                for asset in assets_by_document[item.doc_id]
                if asset.id == image_asset_id
            ),
            None,
        )
        slide_asset = image_asset or next(
            (
                asset
                for asset in assets_by_document[item.doc_id]
                if asset.source_kind == "pptx_slide" and asset.page in {item.page_start, item.page_end}
            ),
            None,
        )
        items.append(
            review_item_response(
                item,
                image_asset_id=slide_asset.id if slide_asset else None,
                image_source_kind=slide_asset.source_kind if slide_asset else None,
                image_description=image_item_description(parsed_item_from_dict(parsed_item))
                if parsed_item and "ocr_image_consolidated" in item.quality_flags else None,
            )
        )
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
        delivery = IngestDeliveryService(job_repo)
        claimed = delivery.queue_existing_job(
            decision.batch.job_id,
            IngestJobPayload.from_dict(resume_payload),
            expected_statuses=frozenset({"human_review"}),
            event_kind="review_resume",
            increment_review_resume=True,
        )
        resume_claimed = claimed.changed and claimed.job is not None
        if resume_claimed:
            _dispatch_best_effort(delivery, queue, decision.batch.job_id)
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


def _dispatch_best_effort(
    delivery: IngestDeliveryService,
    queue: IngestQueue,
    job_id: str,
) -> None:
    try:
        dispatch_pending_deliveries(delivery, queue, limit=1)
    except Exception:
        logger.warning(
            "ingestion delivery deferred job_id=%s event_kind=review_resume",
            job_id,
        )
