"""Ingestion review worker-facing HTTP contracts."""

from typing import Any, Literal

from pydantic import Field

from rag.shared.contracts.http import ContractModel

class ReviewBlockPayload(ContractModel):
    item_index: int = Field(..., ge=0)
    item_type: str = "text"
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = None
    quality_flags: list[str] = Field(default_factory=list)
    partial_text: str = Field(..., min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ReviewBatchCreateRequest(ContractModel):
    job_id: str
    doc_id: str
    parsed_items: list[dict[str, Any]] = Field(default_factory=list)
    resume_payload: dict[str, Any]
    review_items: list[ReviewBlockPayload] = Field(default_factory=list)


class ReviewBatchCreateResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
    review_batch_id: str


class ReviewBatchParsedItemsResponse(ContractModel):
    parsed_items: list[dict[str, Any]] = Field(default_factory=list)


class ImageReviewCandidatePayload(ContractModel):
    candidate_key: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1, max_length=300)
    source_kind: str = Field(..., min_length=1, max_length=80)
    page: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    page_area_ratio: float | None = Field(default=None, ge=0.0)
    object_path: str = Field(..., min_length=1)
    content_type: str = Field(..., min_length=1)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    content_hash: str = Field(..., min_length=1)
    quality_flags: list[str] = Field(default_factory=list)
    score: int = 0
    recommended: bool = True


class ImageReviewBatchCreateRequest(ContractModel):
    job_id: str
    doc_id: str
    parsed_items: list[dict[str, Any]] = Field(default_factory=list)
    resume_payload: dict[str, Any]
    candidates: list[ImageReviewCandidatePayload] = Field(default_factory=list)


class ImageReviewBatchCreateResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
    image_review_batch_id: str


class ImageReviewApprovedKeysResponse(ContractModel):
    candidate_keys: list[str] = Field(default_factory=list)


class ImageReviewResumeResponse(ContractModel):
    parsed_items: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[ImageReviewCandidatePayload] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)
