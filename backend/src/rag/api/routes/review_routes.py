"""Compatibility facade for feature-owned ingestion review routes."""

from ...ingestion.review_routes import (
    approve_review_item,
    decide_image_review_batch,
    get_image_review_candidate_content,
    list_image_review_batches,
    list_review_queue,
    reject_review_item,
    router,
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
