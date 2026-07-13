"""Composition root for ingestion review HTTP routes."""

from fastapi import APIRouter

from .human_review_routes import (
    approve_review_item,
    list_review_queue,
    reject_review_item,
    router as human_review_router,
)
from .image_review_routes import (
    decide_image_review_batch,
    get_image_review_candidate_content,
    list_image_review_batches,
    router as image_review_router,
)

router = APIRouter()
router.include_router(
    human_review_router, prefix="/review-queue", tags=["review-queue"]
)
router.include_router(
    image_review_router, prefix="/review-queue", tags=["review-queue"]
)

__all__ = [
    "approve_review_item",
    "decide_image_review_batch",
    "get_image_review_candidate_content",
    "list_image_review_batches",
    "list_review_queue",
    "reject_review_item",
    "router",
]
