from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .common import ContractModel


DocType = str
UploadJobState = Literal["scheduled", "queued", "processing", "complete", "failed", "human_review", "cancelled"]
UploadJobStage = Literal[
    "scheduled",
    "queued",
    "reading_file",
    "parsing_document",
    "generating_metadata",
    "chunking_document",
    "embedding_chunks",
    "indexing_vectors",
    "saving_claims",
    "finalizing",
    "complete",
    "failed",
    "human_review",
    "cancelled",
]
UploadJobStepState = Literal["pending", "active", "complete", "failed", "needs_review", "cancelled"]
UploadJobProgressUnit = Literal["pages", "chunks", "vectors", "files", "metadata"]


class UploadMetadata(ContractModel):
    group_path: str = Field(..., min_length=1)
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    effective_date: date | None = None
    expiry_date: date | None = None
    doc_type: DocType | None = Field(default=None, max_length=80)
    supersedes: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=2000)


class UploadResponse(ContractModel):
    job_id: str
    status: Literal["queued"] = "queued"


class UploadJobStep(ContractModel):
    id: UploadJobStage
    label: str
    detail: str
    state: UploadJobStepState


class UploadJobStageProgress(ContractModel):
    unit: UploadJobProgressUnit
    current: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    label: str | None = Field(default=None, max_length=160)


class JobStatusResponse(ContractModel):
    job_id: str
    status: UploadJobState
    progress_pct: int = Field(..., ge=0, le=100)
    stage: UploadJobStage
    stage_label: str
    stage_detail: str
    stage_progress: UploadJobStageProgress | None = None
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    warnings: list[str] = Field(default_factory=list)
    parser_provenance: dict[str, Any] | None = None
    steps: list[UploadJobStep] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
