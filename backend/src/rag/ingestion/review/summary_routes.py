"""HTTP transport for the Review Queue navigation summary."""

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from rag.auth.dependencies import require_review_user
from rag.auth.identity_models import UserRecord
from rag.documents.repository import DocumentRepository, get_document_repository

from .dependencies import get_human_review_repository, get_image_review_repository
from .models import HumanReviewRepository, ImageReviewRepository
from .schemas import ReviewQueueSummaryResponse
from .summary import count_visible_pending_review_documents


router = APIRouter()


@router.get(
    "/summary",
    response_model=ReviewQueueSummaryResponse,
    summary="Summarize visible pending review documents",
)
async def summarize_review_queue(
    user: UserRecord = Depends(require_review_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    human_review_repo: HumanReviewRepository = Depends(get_human_review_repository),
    image_review_repo: ImageReviewRepository = Depends(get_image_review_repository),
) -> ReviewQueueSummaryResponse:
    count = await run_in_threadpool(
        count_visible_pending_review_documents,
        user=user,
        document_repo=document_repo,
        human_review_repo=human_review_repo,
        image_review_repo=image_review_repo,
    )
    return ReviewQueueSummaryResponse(pending_document_count=count)
