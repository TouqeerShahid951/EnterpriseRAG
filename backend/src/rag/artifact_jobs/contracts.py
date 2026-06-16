"""Validated contracts for document planning, evidence, and composition."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..schemas.common import ContractModel
from ..schemas.query import ArtifactFormat
RetrievalMode = Literal["focused_search", "document_scan", "structured_rows", "comparison", "timeline"]
ContentBlockKind = Literal[
    "heading",
    "paragraph",
    "bullet_list",
    "numbered_list",
    "key_value",
    "table",
    "quotation",
    "callout",
    "page_break",
    "section_break",
]


class DocumentPlanSection(ContractModel):
    title: str = Field(..., min_length=1, max_length=160)
    objective: str = Field(..., min_length=1, max_length=1000)
    preferred_blocks: list[ContentBlockKind] = Field(default_factory=list, max_length=8)
    retrieval_queries: list[str] = Field(..., min_length=1, max_length=4)
    retrieval_mode: RetrievalMode = "focused_search"
    coverage_requirement: str = Field(default="relevant_evidence", min_length=1, max_length=120)


class DocumentPlan(ContractModel):
    version: Literal["v2"] = "v2"
    title: str = Field(..., min_length=1, max_length=180)
    purpose: str = Field(..., min_length=1, max_length=1200)
    audience: str = Field(default="General business audience", min_length=1, max_length=240)
    language: str = Field(default="English", min_length=1, max_length=80)
    tone: str = Field(default="professional", min_length=1, max_length=80)
    detail_level: Literal["brief", "standard", "detailed"] = "standard"
    document_type: str = Field(default="report", min_length=1, max_length=80)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)
    sections: list[DocumentPlanSection] = Field(default_factory=list, max_length=24)
    format_requirements: dict[ArtifactFormat, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_sections_without_clarification(self) -> "DocumentPlan":
        if not self.clarification_questions and not self.sections:
            raise ValueError("document plan requires sections when no clarification is needed")
        return self


class EvidenceRecord(ContractModel):
    evidence_id: str = Field(..., min_length=1)
    section_title: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    doc_id: str = Field(..., min_length=1)
    doc_title: str = Field(..., min_length=1)
    chunk_id: str = Field(..., min_length=1)
    page_start: int | None = None
    page_end: int | None = None
    content_type: str = "text"
    text: str = ""
    structured_fields: dict[str, str] = Field(default_factory=dict)
    retrieval_score: float = 0.0
    rerank_score: float | None = None


class EvidenceSection(ContractModel):
    title: str
    objective: str
    retrieval_mode: RetrievalMode
    coverage_requirement: str
    coverage_status: Literal["none", "partial", "sufficient", "complete_scan"]
    records: list[EvidenceRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    searched_query_count: int = Field(default=0, ge=0)
    scanned_document_count: int = Field(default=0, ge=0)
    scanned_chunk_count: int = Field(default=0, ge=0)
    top_k_record_count: int = Field(default=0, ge=0)


class EvidenceManifest(ContractModel):
    version: Literal["v2"] = "v2"
    sections: list[EvidenceSection]
    retrieval_rounds: int = Field(default=1, ge=1, le=2)

    @property
    def records(self) -> list[EvidenceRecord]:
        return [record for section in self.sections for record in section.records]


class KeyValueEntry(ContractModel):
    key: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)
    evidence_ids: list[str] = Field(..., min_length=1)


class ContentListItem(ContractModel):
    text: str = Field(..., min_length=1)
    evidence_ids: list[str] = Field(..., min_length=1)


class ContentTableRow(ContractModel):
    values: list[str]
    evidence_ids: list[str] = Field(..., min_length=1)


class ContentTable(ContractModel):
    headers: list[str] = Field(..., min_length=1)
    rows: list[ContentTableRow] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_row_width(self) -> "ContentTable":
        if any(len(row.values) != len(self.headers) for row in self.rows):
            raise ValueError("table rows must match header width")
        return self


class ContentBlock(ContractModel):
    kind: ContentBlockKind
    text: str | None = None
    items: list[str] = Field(default_factory=list)
    list_items: list[ContentListItem] = Field(default_factory=list)
    entries: list[KeyValueEntry] = Field(default_factory=list)
    table: ContentTable | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    level: int = Field(default=1, ge=1, le=4)
    callout_style: Literal["info", "warning", "decision"] = "info"

    @model_validator(mode="after")
    def validate_payload(self) -> "ContentBlock":
        if self.kind in {"paragraph", "quotation", "callout", "heading"} and not (self.text or "").strip():
            raise ValueError(f"{self.kind} block requires text")
        if self.kind in {"bullet_list", "numbered_list"} and not (self.list_items or self.items):
            raise ValueError(f"{self.kind} block requires items")
        if self.kind == "key_value" and not self.entries:
            raise ValueError("key_value block requires entries")
        if self.kind == "table" and self.table is None:
            raise ValueError("table block requires table data")
        return self


class ContentSection(ContractModel):
    title: str = Field(..., min_length=1)
    blocks: list[ContentBlock] = Field(..., min_length=1)


class EvidenceCitation(ContractModel):
    evidence_id: str
    doc_id: str
    doc_title: str
    chunk_id: str
    page_start: int | None = None
    page_end: int | None = None


class EvidenceBackedContent(ContractModel):
    title: str
    purpose: str
    sections: list[ContentSection] = Field(..., min_length=1)
    citations: list[EvidenceCitation] = Field(..., min_length=1)
    warnings: list[str] = Field(default_factory=list)


class PaginatedDocumentSpec(ContractModel):
    title: str
    subtitle: str | None = None
    sections: list[ContentSection] = Field(..., min_length=1)
    include_references: bool = True
    include_coverage_notes: bool = True


class PresentationSlide(ContractModel):
    title: str
    blocks: list[ContentBlock] = Field(..., min_length=1, max_length=8)
    speaker_notes: str | None = None


class PresentationSpec(ContractModel):
    title: str
    subtitle: str | None = None
    slides: list[PresentationSlide] = Field(..., min_length=1, max_length=80)
    include_references_slide: bool = True


class ArtifactContentBundle(ContractModel):
    version: Literal["v2"] = "v2"
    content: EvidenceBackedContent
    paginated: PaginatedDocumentSpec
    presentation: PresentationSpec


class FormatSpecifications(ContractModel):
    paginated: PaginatedDocumentSpec
    presentation: PresentationSpec


class ArtifactContentValidation(ContractModel):
    passed: bool
    support_score: float = Field(..., ge=0.0, le=1.0)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
