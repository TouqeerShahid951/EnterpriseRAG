"""Response mapping for ingestion review HTTP endpoints."""

from ..core.config import settings
from ..schemas.review import (
    ImageReviewBatch,
    ImageReviewCandidate,
    ImageReviewDecisionResponse,
    ReviewItem,
)
from .review_models import (
    ImageReviewBatchRecord,
    ImageReviewCandidateRecord,
    ReviewItemRecord,
)


def review_item_response(item: ReviewItemRecord) -> ReviewItem:
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


def image_review_batch_response(
    batch: ImageReviewBatchRecord,
    candidates: list[ImageReviewCandidateRecord],
) -> ImageReviewBatch:
    pending_count = sum(1 for candidate in candidates if candidate.status == "pending")
    approved_count = sum(
        1 for candidate in candidates if candidate.status == "approved"
    )
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
        candidates=[
            image_review_candidate_response(candidate) for candidate in candidates
        ],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def image_review_candidate_response(
    candidate: ImageReviewCandidateRecord,
) -> ImageReviewCandidate:
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


def image_review_decision_response(
    batch_id: str,
    batch_status: str,
    batch_complete: bool,
    candidates: list[ImageReviewCandidateRecord],
) -> ImageReviewDecisionResponse:
    return ImageReviewDecisionResponse(
        batch_id=batch_id,
        batch_status=batch_status,  # type: ignore[arg-type]
        batch_complete=batch_complete,
        approved_count=sum(
            1 for candidate in candidates if candidate.status == "approved"
        ),
        skipped_count=sum(
            1 for candidate in candidates if candidate.status == "skipped"
        ),
        pending_count=sum(
            1 for candidate in candidates if candidate.status == "pending"
        ),
    )
