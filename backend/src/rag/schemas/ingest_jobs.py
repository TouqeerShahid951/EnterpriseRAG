"""Public ingestion job history contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ContractModel
from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .upload import JobStatusResponse, UploadJobState


IngestJobOrigin = Literal["upload", "reingest", "restore", "folder", "connector", "unknown"]


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


class GraphRAGWorkerState(ContractModel):
    name: str
    pool_size: int = Field(..., ge=0)
    active_jobs: int = Field(..., ge=0)


class GraphRAGActiveTask(ContractModel):
    task_id: str
    task_name: str
    worker: str
    job_id: str | None = None
    document_id: str | None = None
    started_at: datetime | None = None
    elapsed_seconds: int | None = None


class GraphRAGQueuedTask(ContractModel):
    task_id: str
    task_name: str
    job_id: str | None = None
    document_id: str | None = None


class GraphRAGStatusResponse(ContractModel):
    enabled: bool
    queue_name: str
    queued_jobs: int | None = None
    queue_error: str | None = None
    worker_online: bool = False
    worker_error: str | None = None
    active_jobs: int = 0
    observed_pool_size: int = 0
    workers: list[GraphRAGWorkerState] = Field(default_factory=list)
    active_tasks: list[GraphRAGActiveTask] = Field(default_factory=list)
    queued_tasks: list[GraphRAGQueuedTask] = Field(default_factory=list)


class GraphRAGCancelRequest(ContractModel):
    task_id: str = Field(..., min_length=1, max_length=200)


class GraphRAGCancelResponse(ContractModel):
    task_id: str
    job_id: str
    document_id: str
    status: Literal["cancelled"] = "cancelled"
    message: str


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
