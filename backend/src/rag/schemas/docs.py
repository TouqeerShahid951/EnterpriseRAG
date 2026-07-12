from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .common import ContractModel
from ..documents.upload_schemas import DocType, UploadJobState


class DocumentEntity(ContractModel):
    text: str
    type: str
    start: int | None = None
    end: int | None = None


class DocumentCrossReference(ContractModel):
    ref_text: str
    ref_type: str
    position: int | None = None


class DocumentClaim(ContractModel):
    id: str | None = None
    chunk_id: str
    entity: str
    attribute: str
    value: str


class Document(ContractModel):
    id: str
    title: str
    doc_type: DocType | None = None
    group_path: str
    owner_group_path: str
    shared_group_paths: list[str] = Field(default_factory=list)
    access_group_paths: list[str] = Field(default_factory=list)
    governance_owner: Literal["space", "system"] = "space"
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    effective_date: str | None = None
    expiry_date: str | None = None
    description: str | None = None
    summary: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    llm_topics: list[str] = Field(default_factory=list)
    metadata_version: int | None = None
    metadata_confidence: dict[str, Any] = Field(default_factory=dict)
    metadata_provenance: dict[str, Any] = Field(default_factory=dict)
    auto_doc_type: str | None = None
    extracted_dates: dict[str, Any] = Field(default_factory=dict)
    metadata_flags: dict[str, Any] = Field(default_factory=dict)
    entities: list[DocumentEntity] = Field(default_factory=list)
    cross_references: list[DocumentCrossReference] = Field(default_factory=list)
    claims: list[DocumentClaim] = Field(default_factory=list)
    is_current: bool
    ingest_status: UploadJobState
    uploaded_by: str
    superseded_by: str | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None

class DocumentListResponse(ContractModel):
    items: list[Document] = Field(default_factory=list)
    total: int = Field(..., ge=0)


class DocumentClearanceUpdateRequest(ContractModel):
    clearance_level: ClearanceLevel


class DocumentTopicsUpdateRequest(ContractModel):
    topics: list[str] = Field(default_factory=list, max_length=32)
    llm_topics: list[str] = Field(default_factory=list, max_length=32)


class DocumentSharesUpdateRequest(ContractModel):
    group_paths: list[str] = Field(default_factory=list, max_length=128)


class DocumentOwnerUpdateRequest(ContractModel):
    group_path: str = Field(..., min_length=1)


class DocumentUnshareRequest(ContractModel):
    group_path: str = Field(..., min_length=1)


class DocumentSharesResponse(ContractModel):
    document_id: str
    owner_group_path: str
    shared_group_paths: list[str] = Field(default_factory=list)
    access_group_paths: list[str] = Field(default_factory=list)
    governance_owner: Literal["space", "system"] = "space"


class SupersedeRequest(ContractModel):
    supersedes: list[str] = Field(default_factory=list)


class VersionNode(ContractModel):
    id: str
    effective_date: str | None = None
    is_current: bool
    superseded_by: str | None = None


class VersionChainResponse(ContractModel):
    document_id: str
    chain: list[VersionNode] = Field(default_factory=list)


class DeleteDocumentResponse(ContractModel):
    id: str
    status: Literal["soft_deleted", "permanently_deleted"] = "soft_deleted"


class DocumentReingestResponse(ContractModel):
    document_id: str
    job_id: str
    status: Literal["queued"] = "queued"


class DocumentReingestRequest(ContractModel):
    retry_of_job_id: str | None = None


class DocumentGraphEnrichmentResponse(ContractModel):
    document_id: str
    job_id: str
    status: Literal["queued"] = "queued"
    message: str = "Graph enrichment queued."
