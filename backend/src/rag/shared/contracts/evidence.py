"""Citation, attribution, and conflict evidence contracts shared by features."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rag.shared.contracts.http import ContractModel
from .clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL

PARTIAL_NOTICE = (
    "This answer covers only the parts I could verify from the available evidence."
)


class HighlightRange(ContractModel):
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "HighlightRange":
        if self.end <= self.start:
            raise ValueError("highlight range end must be greater than start")
        return self


class TextCitationTarget(ContractModel):
    provenance_kind: str = "unknown"
    kind: Literal["text"] = "text"
    exact_text: str = Field(..., min_length=1)
    prefix: str = ""
    suffix: str = ""
    occurrence: int = Field(default=0, ge=0)


class PageCitationTarget(ContractModel):
    provenance_kind: str = "unknown"
    kind: Literal["page"] = "page"
    page: int = Field(..., ge=1)
    bbox: list[float] = Field(..., min_length=4, max_length=4)
    exact_text: str = ""
    region_type: str = "text"
    confidence: float | None = None
    image_asset_id: str | None = None
    image_source_kind: str | None = None
    extraction_method: str | None = None


class SlideCitationTarget(PageCitationTarget):
    kind: Literal["slide"] = "slide"


class ImageCitationTarget(ContractModel):
    provenance_kind: str = "unknown"
    kind: Literal["image"] = "image"
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    exact_text: str = ""
    confidence: float | None = None
    image_asset_id: str | None = None
    image_source_kind: str | None = None
    extraction_method: str | None = None

    @model_validator(mode="after")
    def validate_location(self) -> "ImageCitationTarget":
        if self.bbox is None and not self.image_asset_id:
            raise ValueError(
                "image citation target requires a bounding box or image asset"
            )
        return self


class SpreadsheetCitationTarget(ContractModel):
    provenance_kind: str = "unknown"
    kind: Literal["spreadsheet"] = "spreadsheet"
    sheet_name: str = Field(..., min_length=1)
    start_row: int = Field(..., ge=0)
    end_row: int = Field(..., ge=1)
    start_column: int = Field(..., ge=0)
    end_column: int = Field(..., ge=1)
    exact_text: str = ""

    @model_validator(mode="after")
    def validate_range(self) -> "SpreadsheetCitationTarget":
        if self.end_row <= self.start_row or self.end_column <= self.start_column:
            raise ValueError("spreadsheet citation target range must be nonempty")
        return self


class JsonCitationTarget(ContractModel):
    provenance_kind: str = "unknown"
    kind: Literal["json"] = "json"
    pointer: str
    exact_text: str = ""


class RecordCitationTarget(ContractModel):
    provenance_kind: str = "unknown"
    kind: Literal["record"] = "record"
    record_id: str = Field(..., min_length=1)
    fields: list[str] = Field(default_factory=list)
    exact_text: str = ""


CitationTarget = Annotated[
    TextCitationTarget
    | PageCitationTarget
    | SlideCitationTarget
    | ImageCitationTarget
    | SpreadsheetCitationTarget
    | JsonCitationTarget
    | RecordCitationTarget,
    Field(discriminator="kind"),
]


class EvidenceField(ContractModel):
    label: str
    value: str
    supports_claim: bool = False


class EvidenceWindow(ContractModel):
    claim_id: str
    claim: str
    kind: Literal["text", "table_row"] = "text"
    passage: str
    highlight_ranges: list[HighlightRange] = Field(default_factory=list)
    support_status: Literal["verified", "source_matched", "semantic_fallback"]
    support_score: float = Field(..., ge=0.0, le=1.0)
    source_start: int = Field(..., ge=0)
    source_end: int = Field(..., ge=0)
    quote_start: int | None = Field(default=None, ge=0)
    quote_end: int | None = Field(default=None, ge=0)
    truncated_start: bool = False
    truncated_end: bool = False
    table_title: str | None = None
    fields: list[EvidenceField] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_offsets(self) -> "EvidenceWindow":
        if self.source_end <= self.source_start:
            raise ValueError("evidence source end must be greater than start")
        if (self.quote_start is None) != (self.quote_end is None):
            raise ValueError("evidence quote offsets must be provided together")
        if self.quote_start is not None and self.quote_end is not None:
            if self.quote_end <= self.quote_start:
                raise ValueError("evidence quote end must be greater than start")
            if self.quote_start < self.source_start or self.quote_end > self.source_end:
                raise ValueError(
                    "evidence quote must be contained by the source window"
                )
        if any(item.end > len(self.passage) for item in self.highlight_ranges):
            raise ValueError("evidence highlight must be contained by the passage")
        return self


class SourceAnchor(ContractModel):
    doc_id: str
    doc_title: str
    chunk_id: str
    page: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    excerpt: str
    group_path: str
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    effective_date: str | None = None
    index_generation_id: str | None = None
    content_hash: str | None = None
    evidence_hash: str | None = None
    provenance_kind: Literal["native", "ocr", "structured", "generated", "unknown"] = "unknown"
    citation_protocol_version: Literal[1] | None = None
    canonical_excerpt: str | None = Field(default=None, exclude=True)
    prompt_context: str | None = Field(default=None, exclude=True)
    quote_texts: list[str] | None = Field(default=None, exclude=True)
    highlight_ranges: list[HighlightRange] = Field(default_factory=list)
    citation_targets: list[CitationTarget] = Field(default_factory=list)
    evidence_windows: list[EvidenceWindow] = Field(default_factory=list)
    attribution_status: Literal["pending", "complete", "unavailable"] = "pending"
    attribution_kind: Literal["text", "table_row"] = Field(default="text", exclude=True)
    attribution_table_title: str = Field(default="", exclude=True)
    attribution_fields: list[EvidenceField] = Field(default_factory=list, exclude=True)


class EvidenceQuote(ContractModel):
    source_label: str
    text: str = Field(min_length=1, max_length=600)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "EvidenceQuote":
        if self.source_end <= self.source_start:
            raise ValueError("quote range must be nonempty")
        return self


class CitationClaim(ContractModel):
    claim_id: str
    answer_start: int = Field(ge=0)
    answer_end: int = Field(ge=0)
    text: str
    source_labels: list[str] = Field(default_factory=list)
    verdict: Literal["supported", "unsupported", "unknown"] = "unknown"
    reason: str | None = None
    quotes: list[EvidenceQuote] = Field(default_factory=list)


class CitationVerification(ContractModel):
    version: Literal[1] = 1
    offset_unit: Literal["unicode_code_point"] = "unicode_code_point"
    answer_sha256: str
    status: Literal["verified", "source_matched", "unverified", "abstained", "unavailable", "not_applicable"]
    repair_count: int = Field(default=0, ge=0, le=1)
    claims: list[CitationClaim] = Field(default_factory=list)


class ConflictPair(ContractModel):
    claim_a_id: str
    claim_b_id: str
    doc_a_id: str
    doc_b_id: str
    chunk_a_id: str
    chunk_b_id: str
    entity: str
    attribute: str
    value_a: str
    value_b: str
    effective_date_a: str | None = None
    effective_date_b: str | None = None
    source_a: SourceAnchor
    source_b: SourceAnchor
