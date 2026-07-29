from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from rag.shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from rag.shared.contracts.http import ContractModel
from rag.documents.upload.schemas import DocType, UploadJobState


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


class DocumentGroupCount(ContractModel):
    group_path: str
    count: int = Field(..., ge=0)


class DocumentCatalogSummary(ContractModel):
    groups: list[DocumentGroupCount] = Field(default_factory=list)
    total: int = Field(..., ge=0)


class DocumentOverviewAttentionItem(ContractModel):
    id: str
    title: str
    group_path: str
    ingest_status: UploadJobState | Literal["unknown"]


class DocumentOverviewSpace(ContractModel):
    group_path: str
    library_documents: int = Field(..., ge=0)
    current_versions: int = Field(..., ge=0)
    processing_current: int = Field(..., ge=0)
    review_current: int = Field(..., ge=0)
    failed_current: int = Field(..., ge=0)
    unknown_current: int = Field(..., ge=0)


class DocumentOverviewResponse(ContractModel):
    library_documents: int = Field(..., ge=0)
    current_versions: int = Field(..., ge=0)
    indexed_current: int = Field(..., ge=0)
    processing_current: int = Field(..., ge=0)
    review_current: int = Field(..., ge=0)
    failed_current: int = Field(..., ge=0)
    unknown_current: int = Field(..., ge=0)
    needs_attention: int = Field(..., ge=0)
    superseded_versions: int = Field(..., ge=0)
    expiring_soon_current: int = Field(..., ge=0)
    trash: int = Field(..., ge=0)
    attention_documents: list[DocumentOverviewAttentionItem] = Field(
        default_factory=list
    )
    spaces: list[DocumentOverviewSpace] = Field(default_factory=list)
