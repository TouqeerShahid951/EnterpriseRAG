from fastapi import APIRouter, Depends, HTTPException, Response, status

from ...auth.document_access import can_write_document
from ...auth.dependencies import require_review_user
from ...core.config import settings
from ...repositories.document_models import ImageReviewBatchRecord, ImageReviewCandidateRecord, ReviewItemRecord
from ...repositories.documents import DocumentRepository, get_document_repository
from ...repositories.identity import UserRecord
from ...schemas.review import (
    ImageReviewBatch,
    ImageReviewCandidate,
    ImageReviewDecisionRequest,
    ImageReviewDecisionResponse,
    ImageReviewQueueResponse,
    ReviewApproveRequest,
    ReviewDecisionResponse,
    ReviewItem,
    ReviewQueueResponse,
)
from ...services.document_image_asset_storage import DocumentImageAssetStorage, get_document_image_asset_storage
from ...ingestion.contracts import IngestJobPayload
from ...ingestion.queue import IngestQueue, get_ingest_queue

router = APIRouter(prefix="/review-queue", tags=["review-queue"])


@router.get("", response_model=ReviewQueueResponse, summary="List human review items")
async def list_review_queue(
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> ReviewQueueResponse:
    items = [
        _review_item_response(item)
        for item in document_repo.list_review_items(status="pending")
        if _can_review_document(user, document_repo, item.doc_id)
    ]
    return ReviewQueueResponse(items=items, total=len(items))


@router.get("/image-batches", response_model=ImageReviewQueueResponse, summary="List PDF image review batches")
async def list_image_review_batches(
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> ImageReviewQueueResponse:
    batches = []
    candidate_total = 0
    for batch in document_repo.list_image_review_batches(status="pending"):
        if not _can_review_document(user, document_repo, batch.doc_id):
            continue
        candidates = document_repo.list_image_review_candidates_for_batch(batch.id)
        candidate_total += len(candidates)
        batches.append(_image_review_batch_response(batch, candidates))
    return ImageReviewQueueResponse(batches=batches, total=len(batches), candidate_total=candidate_total)


@router.get("/image-candidates/{candidate_id}/content", summary="Read PDF image review candidate content")
async def get_image_review_candidate_content(
    candidate_id: str,
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    image_storage: DocumentImageAssetStorage = Depends(get_document_image_asset_storage),
) -> Response:
    candidate = document_repo.get_image_review_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "image_review_candidate_not_found", "message": "Image review candidate was not found."},
        )
    _require_review_document_scope(user, document_repo, candidate.doc_id)
    try:
        content = image_storage.read(candidate.object_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "image_review_candidate_content_unavailable", "message": "Image review candidate image is unavailable."},
        ) from exc
    headers = {"Content-Disposition": f'inline; filename="{content.filename}"'}
    return Response(content=content.content, media_type=content.content_type, headers=headers)


@router.post(
    "/image-batches/{batch_id}/decisions",
    response_model=ImageReviewDecisionResponse,
    summary="Approve or skip PDF image candidates and resume ingestion",
)
async def decide_image_review_batch(
    batch_id: str,
    payload: ImageReviewDecisionRequest,
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> ImageReviewDecisionResponse:
    if not (payload.approve_candidate_ids or payload.skip_candidate_ids or payload.approve_recommended or payload.skip_remaining):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_image_review_decision", "message": "Choose at least one image review decision."},
        )
    batch = document_repo.get_image_review_batch(batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "image_review_batch_not_found", "message": "Image review batch was not found."},
        )
    _require_review_document_scope(user, document_repo, batch.doc_id)
    decision = document_repo.apply_image_review_decisions(
        batch_id,
        approve_candidate_ids=payload.approve_candidate_ids,
        skip_candidate_ids=payload.skip_candidate_ids,
        approve_recommended=payload.approve_recommended,
        skip_remaining=payload.skip_remaining,
        reviewer_id=user.id,
    )
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "image_review_batch_not_found", "message": "Image review batch was not found."},
        )
    if decision.batch_complete:
        job = document_repo.get_ingest_job(decision.batch.job_id)
        if job is not None and job.status == "cancelled":
            document_repo.append_audit_event(
                event_type="image_review.resume_skipped",
                actor_id=user.id,
                target_type="image_review_batch",
                target_id=decision.batch.id,
                payload={"doc_id": decision.batch.doc_id, "reason": "ingest_cancelled"},
            )
        else:
            resume_payload = dict(decision.batch.resume_payload)
            resume_payload["image_review_batch_id"] = decision.batch.id
            try:
                queue.enqueue(IngestJobPayload.from_dict(resume_payload))
                document_repo.update_ingest_job(decision.batch.job_id, status="queued", progress_pct=0)
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "queue_unavailable", "message": "Upload queue is unavailable."},
                ) from exc
    document_repo.append_audit_event(
        event_type="image_review.decided",
        actor_id=user.id,
        target_type="image_review_batch",
        target_id=decision.batch.id,
        payload={
            "doc_id": decision.batch.doc_id,
            "batch_complete": decision.batch_complete,
            "changed_count": len(decision.candidates),
        },
    )
    candidates = document_repo.list_image_review_candidates_for_batch(decision.batch.id)
    return _image_review_decision_response(decision.batch.id, decision.batch.status, decision.batch_complete, candidates)


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
    _require_visible_pending_review_item(user, document_repo, item_id)
    decision = document_repo.approve_review_item(item_id, corrected_text=payload.corrected_text, reviewer_id=user.id)
    if decision is None:
        raise HTTPException(status_code=404, detail={"code": "review_item_not_found", "message": "Review item was not found."})
    if decision.batch_complete:
        job = document_repo.get_ingest_job(decision.batch.job_id)
        if job is not None and job.status == "cancelled":
            document_repo.append_audit_event(
                event_type="review.resume_skipped",
                actor_id=user.id,
                target_type="review_item",
                target_id=decision.item.id,
                payload={"batch_id": decision.batch.id, "doc_id": decision.batch.doc_id, "reason": "ingest_cancelled"},
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
        try:
            queue.enqueue(IngestJobPayload.from_dict(resume_payload))
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
    _require_visible_pending_review_item(user, document_repo, item_id)
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


def _require_visible_pending_review_item(user: UserRecord, document_repo: DocumentRepository, item_id: str) -> ReviewItemRecord:
    item = next((item for item in document_repo.list_review_items(status="pending") if item.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "review_item_not_found", "message": "Review item was not found."})
    _require_review_document_scope(user, document_repo, item.doc_id)
    return item


def _require_review_document_scope(user: UserRecord, document_repo: DocumentRepository, doc_id: str) -> None:
    if not _can_review_document(user, document_repo, doc_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "review_scope_forbidden", "message": "Review item is outside your Knowledge Space or clearance scope."},
        )


def _can_review_document(user: UserRecord, document_repo: DocumentRepository, doc_id: str) -> bool:
    document = document_repo.get_document(doc_id)
    return document is not None and can_write_document(user, document)


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


def _image_review_batch_response(batch: ImageReviewBatchRecord, candidates: list[ImageReviewCandidateRecord]) -> ImageReviewBatch:
    pending_count = sum(1 for candidate in candidates if candidate.status == "pending")
    approved_count = sum(1 for candidate in candidates if candidate.status == "approved")
    skipped_count = sum(1 for candidate in candidates if candidate.status == "skipped")
    return ImageReviewBatch(
        id=batch.id,
        job_id=batch.job_id,
        doc_id=batch.doc_id,
        doc_title=batch.doc_title,
        status=batch.status,  # type: ignore[arg-type]
        candidate_count=batch.candidate_count,
        recommended_count=batch.recommended_count,
        pending_count=pending_count,
        approved_count=approved_count,
        skipped_count=skipped_count,
        candidates=[_image_review_candidate_response(candidate) for candidate in candidates],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def _image_review_candidate_response(candidate: ImageReviewCandidateRecord) -> ImageReviewCandidate:
    return ImageReviewCandidate(
        id=candidate.id,
        batch_id=candidate.batch_id,
        doc_id=candidate.doc_id,
        doc_title=candidate.doc_title,
        candidate_key=candidate.candidate_key,
        filename=candidate.filename,
        source_kind=candidate.source_kind,
        page=candidate.page,
        bbox=candidate.bbox,
        page_area_ratio=candidate.page_area_ratio,
        content_url=f"{settings.public_api_prefix}/review-queue/image-candidates/{candidate.id}/content",
        content_type=candidate.content_type,
        width=candidate.width,
        height=candidate.height,
        quality_flags=list(candidate.quality_flags),
        score=candidate.score,
        recommended=candidate.recommended,
        status=candidate.status,  # type: ignore[arg-type]
        assigned_to=candidate.assigned_to,
        skip_reason=candidate.skip_reason,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def _image_review_decision_response(
    batch_id: str,
    batch_status: str,
    batch_complete: bool,
    candidates: list[ImageReviewCandidateRecord],
) -> ImageReviewDecisionResponse:
    return ImageReviewDecisionResponse(
        batch_id=batch_id,
        batch_status=batch_status,  # type: ignore[arg-type]
        batch_complete=batch_complete,
        approved_count=sum(1 for candidate in candidates if candidate.status == "approved"),
        skipped_count=sum(1 for candidate in candidates if candidate.status == "skipped"),
        pending_count=sum(1 for candidate in candidates if candidate.status == "pending"),
    )
