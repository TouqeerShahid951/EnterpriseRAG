"""Public ingestion job history contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from rag.shared.contracts.http import ContractModel
from rag.shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from rag.documents.upload.schemas import JobStatusResponse, UploadJobState


IngestJobOrigin = Literal["upload", "reingest", "restore", "folder", "connector", "unknown"]


class IngestJobItem(JobStatusResponse):
    document_id: str
    document_title: str
    retry_of_job_id: str | None = None
    group_path: str
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    origin: IngestJobOrigin
    uploaded_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class IngestJobListResponse(ContractModel):
    items: list[IngestJobItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class IngestJobSummaryResponse(ContractModel):
    total: int = 0
    active: int = 0
    needs_attention: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    stage_counts: dict[str, int] = Field(default_factory=dict)
    origin_counts: dict[str, int] = Field(default_factory=dict)


class StaleIngestJobItem(ContractModel):
    job_id: str
    document_id: str
    document_title: str
    group_path: str
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    attempt_count: int
    max_attempts: int
    last_activity_at: datetime | None = None
    stale_for_seconds: int
    recoverable: bool
    recovery_code: str | None = None
    recovery_message: str


class StaleIngestJobListResponse(ContractModel):
    items: list[StaleIngestJobItem] = Field(default_factory=list)
    total: int = 0
    recoverable: int = 0
    stale_after_seconds: int


class IngestJobRecoveryResponse(ContractModel):
    job_id: str
    status: Literal["queued"] = "queued"
    next_attempt: int
    message: str


class IngestJobCancelResponse(ContractModel):
    job_id: str
    status: UploadJobState
    message: str


class DocumentReingestResponse(ContractModel):
    document_id: str
    job_id: str
    status: Literal["queued"] = "queued"


class DocumentReingestRequest(ContractModel):
    retry_of_job_id: str | None = None


class SpreadsheetColumnReview(ContractModel):
    index: int = Field(..., ge=0, lt=256)
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default="mixed", max_length=40)
    description: str = Field(default="", max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not (cleaned := " ".join(value.split())):
            raise ValueError("column name must not be blank")
        return cleaned

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, values: list[str]) -> list[str]:
        aliases = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > 80 for value in aliases):
            raise ValueError("aliases must contain 1 to 80 characters")
        if len({value.lower() for value in aliases}) != len(aliases):
            raise ValueError("aliases must be unique")
        return aliases


class SpreadsheetSheetReview(ContractModel):
    source_name: str = Field(..., min_length=1, max_length=200)
    table_name: str = Field(..., min_length=1, max_length=200)
    header_rows: list[int] = Field(..., min_length=1, max_length=3)
    header_candidates: list[int] = Field(default_factory=list, max_length=10)
    excluded: bool = False
    description: str = Field(default="", max_length=500)
    columns: list[SpreadsheetColumnReview] = Field(default_factory=list, max_length=256)

    @field_validator("source_name", "table_name")
    @classmethod
    def validate_names(cls, value: str) -> str:
        if not (cleaned := " ".join(value.split())):
            raise ValueError("sheet and table names must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_rows_and_columns(self) -> "SpreadsheetSheetReview":
        if self.header_rows != sorted(set(self.header_rows)) or any(row < 1 for row in self.header_rows):
            raise ValueError("header_rows must contain unique positive row numbers in ascending order")
        if len({column.index for column in self.columns}) != len(self.columns):
            raise ValueError("column indexes must be unique within a sheet")
        return self


class SpreadsheetReviewRequest(ContractModel):
    sheets: list[SpreadsheetSheetReview] = Field(..., min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_sheets(self) -> "SpreadsheetReviewRequest":
        if len({sheet.source_name for sheet in self.sheets}) != len(self.sheets):
            raise ValueError("sheet source names must be unique")
        if all(sheet.excluded for sheet in self.sheets):
            raise ValueError("at least one sheet must be included")
        return self


class SpreadsheetReviewResponse(SpreadsheetReviewRequest):
    document_id: str


class SpreadsheetReviewUpdateResponse(DocumentReingestResponse):
    pass
