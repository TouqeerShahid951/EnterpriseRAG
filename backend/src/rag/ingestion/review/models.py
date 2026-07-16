"""Human- and image-review persistence contracts and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ReviewBatchRecord:
    id: str
    job_id: str
    doc_id: str
    status: str
    parsed_items: list[dict[str, Any]]
    resume_payload: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ReviewItemRecord:
    id: str
    batch_id: str
    doc_id: str
    doc_title: str
    item_index: int
    item_type: str
    page_start: int | None
    page_end: int | None
    bbox: list[float] | None
    quality_flags: tuple[str, ...]
    partial_text: str
    corrected_text: str | None
    confidence: float | None
    status: str
    assigned_to: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ReviewDecisionRecord:
    item: ReviewItemRecord
    batch: ReviewBatchRecord
    batch_complete: bool = False


@dataclass(frozen=True)
class ImageReviewBatchRecord:
    id: str
    job_id: str
    doc_id: str
    doc_title: str
    status: str
    parsed_items: list[dict[str, Any]]
    resume_payload: dict[str, Any]
    candidate_count: int
    recommended_count: int
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ImageReviewCandidateRecord:
    id: str
    batch_id: str
    doc_id: str
    doc_title: str
    candidate_key: str
    filename: str
    source_kind: str
    page: int | None
    bbox: list[float] | None
    page_area_ratio: float | None
    object_path: str
    content_type: str
    width: int | None
    height: int | None
    content_hash: str
    quality_flags: tuple[str, ...]
    score: int
    recommended: bool
    status: str
    assigned_to: str | None
    skip_reason: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ImageReviewDecisionRecord:
    batch: ImageReviewBatchRecord
    candidates: tuple[ImageReviewCandidateRecord, ...]
    batch_complete: bool = False


class ImageReviewBatchClosedError(RuntimeError):
    def __init__(self, batch_id: str, status: str) -> None:
        self.batch_id = batch_id
        self.status = status
        super().__init__(f"image review batch {batch_id} is {status}")


@runtime_checkable
class HumanReviewRepository(Protocol):
    def create_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        review_items: list[dict[str, Any]],
    ) -> ReviewBatchRecord: ...

    def get_review_batch(self, batch_id: str) -> ReviewBatchRecord | None: ...

    def list_review_items(self, *, status: str = "pending") -> list[ReviewItemRecord]: ...

    def list_review_items_for_batch(self, batch_id: str) -> list[ReviewItemRecord]: ...

    def approve_review_item(
        self,
        item_id: str,
        *,
        corrected_text: str,
        reviewer_id: str,
    ) -> ReviewDecisionRecord | None: ...

    def reject_review_item(
        self,
        item_id: str,
        *,
        reviewer_id: str,
    ) -> ReviewDecisionRecord | None: ...


@runtime_checkable
class ImageReviewRepository(Protocol):
    def create_image_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> ImageReviewBatchRecord: ...

    def get_image_review_batch(self, batch_id: str) -> ImageReviewBatchRecord | None: ...

    def list_image_review_batches(
        self,
        *,
        status: str = "pending",
    ) -> list[ImageReviewBatchRecord]: ...

    def list_image_review_candidates_for_batch(
        self,
        batch_id: str,
        *,
        status: str | None = None,
    ) -> list[ImageReviewCandidateRecord]: ...

    def get_image_review_candidate(
        self,
        candidate_id: str,
    ) -> ImageReviewCandidateRecord | None: ...

    def apply_image_review_decisions(
        self,
        batch_id: str,
        *,
        approve_candidate_ids: list[str],
        skip_candidate_ids: list[str],
        reviewer_id: str,
        approve_recommended: bool = False,
        skip_remaining: bool = False,
    ) -> ImageReviewDecisionRecord | None: ...

    def get_image_review_approved_keys(self, batch_id: str) -> list[str]: ...
