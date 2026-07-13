"""HTTP workflows for PDF image review."""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..auth.dependencies import require_review_user
from ..auth.identity_models import UserRecord
from ..documents.repository import DocumentRepository, get_document_repository
from ..schemas.review import (
    ImageReviewDecisionRequest,
    ImageReviewDecisionResponse,
    ImageReviewQueueResponse,
)
from ..services.document_image_asset_storage import (
    DocumentImageAssetStorage,
    get_document_image_asset_storage,
)
from .contracts import IngestJobPayload
from .job_dependencies import get_ingest_job_repository
from .job_models import IngestJobRepository
from .queue import IngestQueue, get_ingest_queue
from .review_access import can_review_document, require_review_document_scope
from .review_dependencies import get_image_review_repository
from .review_models import ImageReviewBatchClosedError, ImageReviewRepository
from .review_presenters import (
    image_review_batch_response,
    image_review_decision_response,
)

router = APIRouter()


@router.get(
    "/image-batches",
    response_model=ImageReviewQueueResponse,
    summary="List PDF image review batches",
)
async def list_image_review_batches(
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    image_review_repo: ImageReviewRepository = Depends(get_image_review_repository),
) -> ImageReviewQueueResponse:
    batches = []
    candidate_total = 0
    for batch in image_review_repo.list_image_review_batches(status="pending"):
        if not can_review_document(user, document_repo, batch.doc_id):
            continue
        candidates = image_review_repo.list_image_review_candidates_for_batch(batch.id)
        candidate_total += len(candidates)
        batches.append(image_review_batch_response(batch, candidates))
    return ImageReviewQueueResponse(
        batches=batches, total=len(batches), candidate_total=candidate_total
    )


@router.get(
    "/image-candidates/{candidate_id}/content",
    summary="Read PDF image review candidate content",
)
async def get_image_review_candidate_content(
    candidate_id: str,
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    image_review_repo: ImageReviewRepository = Depends(get_image_review_repository),
    image_storage: DocumentImageAssetStorage = Depends(
        get_document_image_asset_storage
    ),
) -> Response:
    candidate = image_review_repo.get_image_review_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "image_review_candidate_not_found",
                "message": "Image review candidate was not found.",
            },
        )
    require_review_document_scope(user, document_repo, candidate.doc_id)
    try:
        content = image_storage.read(candidate.object_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "image_review_candidate_content_unavailable",
                "message": "Image review candidate image is unavailable.",
            },
        ) from exc
    headers = {"Content-Disposition": f'inline; filename="{content.filename}"'}
    return Response(
        content=content.content, media_type=content.content_type, headers=headers
    )


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
    image_review_repo: ImageReviewRepository = Depends(get_image_review_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> ImageReviewDecisionResponse:
    if not (
        payload.approve_candidate_ids
        or payload.skip_candidate_ids
        or payload.approve_recommended
        or payload.skip_remaining
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "empty_image_review_decision",
                "message": "Choose at least one image review decision.",
            },
        )
    batch = image_review_repo.get_image_review_batch(batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "image_review_batch_not_found",
                "message": "Image review batch was not found.",
            },
        )
    require_review_document_scope(user, document_repo, batch.doc_id)
    try:
        decision = image_review_repo.apply_image_review_decisions(
            batch_id,
            approve_candidate_ids=payload.approve_candidate_ids,
            skip_candidate_ids=payload.skip_candidate_ids,
            approve_recommended=payload.approve_recommended,
            skip_remaining=payload.skip_remaining,
            reviewer_id=user.id,
        )
    except ImageReviewBatchClosedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "image_review_batch_closed",
                "message": "Image review batch is already closed.",
            },
        ) from exc
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "image_review_batch_not_found",
                "message": "Image review batch was not found.",
            },
        )
    resumed = False
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
            if decision.candidates:
                document_repo.append_audit_event(
                    event_type="image_review.resume_skipped",
                    actor_id=user.id,
                    target_type="image_review_batch",
                    target_id=decision.batch.id,
                    payload={
                        "doc_id": decision.batch.doc_id,
                        "reason": "ingest_cancelled",
                    },
                )
        elif job.status == "human_review":
            resume_payload = dict(decision.batch.resume_payload)
            resume_payload["image_review_batch_id"] = decision.batch.id
            claimed = job_repo.update_ingest_job(
                decision.batch.job_id,
                status="queued",
                progress_pct=0,
                expected_statuses=frozenset({"human_review"}),
            )
            if claimed.changed:
                try:
                    queue.enqueue(IngestJobPayload.from_dict(resume_payload))
                    resumed = True
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
    if decision.candidates or resumed:
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
    candidates = image_review_repo.list_image_review_candidates_for_batch(
        decision.batch.id
    )
    return image_review_decision_response(
        decision.batch.id,
        decision.batch.status,
        decision.batch_complete,
        candidates,
    )
