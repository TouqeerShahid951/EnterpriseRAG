from datetime import date, datetime
from typing import Literal

from pydantic import Field

from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .common import ContractModel
from .upload import DocType


FolderSourceType = Literal["snapshot", "minio_prefix"]
FolderScheduleType = Literal["one_time", "recurring"]
FolderScheduleStatus = Literal["scheduled", "active", "paused", "cancelled", "complete", "failed"]
FolderRunStatus = Literal["scheduled", "running", "complete", "failed", "cancelled"]
FolderRunItemStatus = Literal["scheduled", "queued", "skipped", "failed"]


class RecurrenceWindow(ContractModel):
    days_of_week: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6], min_length=1, max_length=7)
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")


class FolderScheduleBase(ContractModel):
    name: str = Field(..., min_length=1, max_length=200)
    group_path: str = Field(..., min_length=1)
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    effective_date: date | None = None
    expiry_date: date | None = None
    doc_type: DocType | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    schedule_type: FolderScheduleType
    timezone: str = "Asia/Karachi"
    scheduled_at: datetime | None = None
    recurrence: RecurrenceWindow | None = None


class MinioPrefixScheduleCreateRequest(FolderScheduleBase):
    bucket: str = Field(..., min_length=1, max_length=255)
    prefix: str = Field(..., min_length=1, max_length=1024)


class FolderScheduleUpdateRequest(ContractModel):
    schedule_type: FolderScheduleType
    timezone: str = "Asia/Karachi"
    scheduled_at: datetime | None = None
    recurrence: RecurrenceWindow | None = None


class FolderScheduleActionResponse(ContractModel):
    id: str
    status: FolderScheduleStatus


class FolderRunItem(ContractModel):
    id: str
    run_id: str
    schedule_id: str
    source_path: str
    filename: str
    content_hash: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    status: FolderRunItemStatus
    skip_code: str | None = None
    skip_message: str | None = None
    document_id: str | None = None
    job_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FolderRun(ContractModel):
    id: str
    schedule_id: str
    status: FolderRunStatus
    due_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    item_count: int = 0
    queued_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


class FolderSchedule(ContractModel):
    id: str
    name: str
    source_type: FolderSourceType
    schedule_type: FolderScheduleType
    status: FolderScheduleStatus
    group_path: str
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    doc_type: DocType | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    description: str | None = None
    timezone: str
    scheduled_at: datetime | None = None
    recurrence: dict[str, object] = Field(default_factory=dict)
    source_config: dict[str, object] = Field(default_factory=dict)
    created_by: str | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_run: FolderRun | None = None


class FolderScheduleListResponse(ContractModel):
    items: list[FolderSchedule] = Field(default_factory=list)
    total: int = Field(..., ge=0)


class FolderRunListResponse(ContractModel):
    items: list[FolderRun] = Field(default_factory=list)
    total: int = Field(..., ge=0)


class FolderRunItemListResponse(ContractModel):
    items: list[FolderRunItem] = Field(default_factory=list)
    total: int = Field(..., ge=0)
