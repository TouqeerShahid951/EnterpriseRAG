from typing import Any, Literal

from pydantic import Field

from .common import ContractModel
from .docs import SupersedeRequest
from .query import ConflictPair
from .upload import DocType, UploadJobStageProgress, UploadJobState


class ServiceTokenContext(ContractModel):
    service_name: str
    scopes: tuple[str, ...] = Field(default_factory=tuple)


class AbacFilterResponse(ContractModel):
    filter: dict[str, Any]


class ClaimRecord(ContractModel):
    id: str | None = None
    doc_id: str
    chunk_id: str
    entity: str
    attribute: str
    value: str


class ClaimsSaveRequest(ContractModel):
    doc_id: str | None = None
    claims: list[ClaimRecord] = Field(default_factory=list)


class ClaimsSaveResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
    saved_count: int = Field(..., ge=0)


class ClaimsIngestResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
    saved_count: int = Field(..., ge=0)
    conflict_count: int = Field(..., ge=0)
    conflicted_claim_ids: list[str] = Field(default_factory=list)


class ClaimsLookupResponse(ContractModel):
    claims: list[ClaimRecord] = Field(default_factory=list)


class ConflictCheckRequest(ContractModel):
    claims: list[ClaimRecord] = Field(default_factory=list)


class ConflictCheckResponse(ContractModel):
    conflicts: list[ConflictPair] = Field(default_factory=list)


class ConflictSaveRequest(ContractModel):
    conflicts: list[ConflictPair] = Field(default_factory=list)


class ConflictSaveResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
    saved_count: int = Field(..., ge=0)


class InternalSupersedeRequest(SupersedeRequest):
    pass


class DocumentEntityPayload(ContractModel):
    text: str
    type: str
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)


class DocumentCrossReferencePayload(ContractModel):
    ref_text: str
    ref_type: str
    position: int | None = Field(default=None, ge=0)


class DocumentMetadataSaveRequest(ContractModel):
    summary: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    llm_topics: list[str] = Field(default_factory=list)
    metadata_version: int | None = Field(default=None, ge=1)
    metadata_confidence: dict[str, Any] = Field(default_factory=dict)
    metadata_provenance: dict[str, Any] = Field(default_factory=dict)
    doc_type: DocType | None = Field(default=None, max_length=80)
    auto_doc_type: str | None = None
    extracted_dates: dict[str, Any] = Field(default_factory=dict)
    metadata_flags: dict[str, Any] = Field(default_factory=dict)
    entities: list[DocumentEntityPayload] = Field(default_factory=list)
    cross_references: list[DocumentCrossReferencePayload] = Field(default_factory=list)


class DocumentImageAssetPayload(ContractModel):
    id: str | None = None
    source_kind: str = Field(..., min_length=1, max_length=80)
    page: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    object_path: str = Field(..., min_length=1)
    content_type: str = Field(..., min_length=1)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    content_hash: str = Field(..., min_length=1)
    extracted_text: str | None = None
    caption: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_flags: list[str] = Field(default_factory=list)


class DocumentImageAssetsReplaceRequest(ContractModel):
    job_id: str
    assets: list[DocumentImageAssetPayload] = Field(default_factory=list)


class DocumentImageAssetsReplaceResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
    saved_count: int = Field(..., ge=0)


class InternalJobStatusRequest(ContractModel):
    run_token: str | None = Field(default=None, min_length=1, max_length=100)
    status: UploadJobState
    progress_pct: int = Field(..., ge=0, le=100)
    stage_progress: UploadJobStageProgress | None = None
    warnings: list[str] | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message_safe: str | None = Field(default=None, max_length=500)


class InternalMutationResponse(ContractModel):
    status: Literal["accepted"] = "accepted"


class InternalJobStatusResponse(ContractModel):
    job_id: str
    doc_id: str
    status: UploadJobState


class InternalJobAttemptRequest(ContractModel):
    run_token: str | None = Field(default=None, min_length=1, max_length=100)


class InternalJobAttemptResponse(ContractModel):
    status: Literal["accepted", "busy", "exhausted"]
    attempt_count: int = Field(..., ge=0)
    max_attempts: int = Field(..., ge=1)
    job_status: str
    run_token: str | None = Field(default=None, max_length=100)


class InternalJobLeaseRequest(ContractModel):
    run_token: str | None = Field(default=None, min_length=1, max_length=100)


class InternalJobEventRequest(ContractModel):
    event_type: str = Field(..., min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class InternalParserProvenanceRequest(ContractModel):
    run_token: str | None = Field(default=None, min_length=1, max_length=100)
    provenance: dict[str, Any] = Field(default_factory=dict)


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


class ImageReviewResumeResponse(ContractModel):
    parsed_items: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[ImageReviewCandidatePayload] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)
