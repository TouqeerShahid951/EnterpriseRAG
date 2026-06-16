"""Public ingestion job history contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ContractModel
from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .upload import JobStatusResponse


IngestJobOrigin = Literal["upload", "reingest", "restore", "folder", "unknown"]


class IngestJobItem(JobStatusResponse):
    document_id: str
    document_title: str
    group_path: str
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    origin: IngestJobOrigin
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
