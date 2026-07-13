"""Citation, attribution, and conflict evidence contracts shared by features."""

from typing import Literal

from pydantic import Field, model_validator

from ...schemas.common import ContractModel
from .clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL


class HighlightRange(ContractModel):
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "HighlightRange":
        if self.end <= self.start:
            raise ValueError("highlight range end must be greater than start")
        return self


class SourceRegion(ContractModel):
    page: int | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    text: str = ""
    region_type: str = "text"
    confidence: float | None = None
    image_asset_id: str | None = None
    image_source_kind: str | None = None
    extraction_method: str | None = None


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
    support_status: Literal["verified", "semantic_fallback"]
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
    highlight_ranges: list[HighlightRange] = Field(default_factory=list)
    source_regions: list[SourceRegion] = Field(default_factory=list)
    evidence_windows: list[EvidenceWindow] = Field(default_factory=list)
    attribution_status: Literal["pending", "complete", "unavailable"] = "pending"
    attribution_kind: Literal["text", "table_row"] = Field(default="text", exclude=True)
    attribution_table_title: str = Field(default="", exclude=True)
    attribution_fields: list[EvidenceField] = Field(default_factory=list, exclude=True)


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
