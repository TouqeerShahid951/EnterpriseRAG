from datetime import datetime
from typing import Literal

from pydantic import Field

from rag.shared.contracts.http import ContractModel


ReviewStatus = Literal["pending", "approved", "rejected"]
ImageReviewCandidateStatus = Literal["pending", "approved", "skipped"]


class ReviewItem(ContractModel):
    id: str
    batch_id: str
    doc_id: str
    doc_title: str
    item_index: int = Field(..., ge=0)
    item_type: str
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = None
    quality_flags: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    partial_text: str
    corrected_text: str | None = None
    status: ReviewStatus = "pending"
    assigned_to: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReviewQueueResponse(ContractModel):
    items: list[ReviewItem] = Field(default_factory=list)
    total: int = Field(..., ge=0)


class ReviewQueueSummaryResponse(ContractModel):
    pending_document_count: int = Field(..., ge=0)


class ReviewApproveRequest(ContractModel):
    corrected_text: str = Field(..., min_length=1)


class ReviewDecisionResponse(ContractModel):
    id: str
    status: ReviewStatus
    batch_id: str
    batch_status: ReviewStatus
    batch_complete: bool = False


class ImageReviewCandidate(ContractModel):
    id: str
    batch_id: str
    doc_id: str
    doc_title: str
    candidate_key: str
    filename: str
    source_kind: str
    page: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = None
    page_area_ratio: float | None = None
    content_url: str
    content_type: str
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    quality_flags: list[str] = Field(default_factory=list)
    score: int = 0
    recommended: bool = True
    status: ImageReviewCandidateStatus = "pending"
    assigned_to: str | None = None
    skip_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ImageReviewBatch(ContractModel):
    id: str
    job_id: str
    doc_id: str
    doc_title: str
    status: ReviewStatus = "pending"
    candidate_count: int = Field(..., ge=0)
    recommended_count: int = Field(..., ge=0)
    pending_count: int = Field(..., ge=0)
    approved_count: int = Field(..., ge=0)
    skipped_count: int = Field(..., ge=0)
    candidates: list[ImageReviewCandidate] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ImageReviewQueueResponse(ContractModel):
    batches: list[ImageReviewBatch] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    candidate_total: int = Field(..., ge=0)


class ImageReviewDecisionRequest(ContractModel):
    approve_candidate_ids: list[str] = Field(default_factory=list)
    skip_candidate_ids: list[str] = Field(default_factory=list)
    approve_recommended: bool = False
    skip_remaining: bool = False


class ImageReviewDecisionResponse(ContractModel):
    batch_id: str
    batch_status: ReviewStatus
    batch_complete: bool
    approved_count: int = Field(..., ge=0)
    skipped_count: int = Field(..., ge=0)
    pending_count: int = Field(..., ge=0)
