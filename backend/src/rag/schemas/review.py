from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ContractModel


ReviewStatus = Literal["pending", "approved", "rejected"]


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


class ReviewApproveRequest(ContractModel):
    corrected_text: str = Field(..., min_length=1)


class ReviewDecisionResponse(ContractModel):
    id: str
    status: ReviewStatus
    batch_id: str
    batch_status: ReviewStatus
    batch_complete: bool = False
