"""Document-owned worker-facing HTTP contracts."""

from typing import Any, Literal

from pydantic import Field

from rag.documents.metadata.schemas import SupersedeRequest
from rag.documents.upload.schemas import DocType
from rag.shared.contracts.evidence import ConflictPair
from rag.shared.contracts.http import ContractModel

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
