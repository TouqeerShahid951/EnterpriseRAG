from datetime import date, datetime
from typing import Literal

from pydantic import Field

from ...schemas.common import ContractModel
from ...shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL


FolderSourceType = Literal[
    "snapshot",
    "local_folder",
    "minio_prefix",
    "connector",
    "sql_server",
    "postgres",
    "mysql",
    "mariadb",
    "mongodb",
    "oracle",
    "opensearch",
    "elasticsearch",
    "redis",
    "cassandra",
    "fake",
]
FolderScheduleType = Literal["one_time", "recurring"]
FolderScheduleStatus = Literal[
    "scheduled", "active", "paused", "cancelled", "complete", "failed"
]
FolderRunStatus = Literal["scheduled", "running", "complete", "failed", "cancelled"]
FolderRunItemStatus = Literal["scheduled", "queued", "skipped", "failed"]
ConnectorIngestionMode = Literal["json_snapshot", "direct_chunks"]
ConnectorDeletionPolicy = Literal[
    "keep_deleted_documents",
    "mark_as_stale",
    "archive_from_retrieval",
    "delete_from_index_after_review",
]


class RecurrenceWindow(ContractModel):
    days_of_week: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5, 6], min_length=1, max_length=7
    )
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")


class FolderScheduleBase(ContractModel):
    name: str = Field(..., min_length=1, max_length=200)
    group_path: str = Field(..., min_length=1)
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    effective_date: date | None = None
    expiry_date: date | None = None
    doc_type: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    schedule_type: FolderScheduleType
    timezone: str = "Asia/Karachi"
    scheduled_at: datetime | None = None
    recurrence: RecurrenceWindow | None = None


class MinioPrefixScheduleCreateRequest(FolderScheduleBase):
    bucket: str = Field(..., min_length=1, max_length=255)
    prefix: str = Field(..., min_length=1, max_length=1024)


class LocalFolderScheduleCreateRequest(FolderScheduleBase):
    path: str = Field(..., min_length=1, max_length=2048)


class LocalFolderDirectory(ContractModel):
    name: str
    path: str
    has_children: bool = False


class LocalFolderListResponse(ContractModel):
    root_path: str
    current_path: str
    parent_path: str | None = None
    items: list[LocalFolderDirectory] = Field(default_factory=list)


class ConnectorScheduleCreateRequest(FolderScheduleBase):
    connector_profile_id: str = Field(..., min_length=1)
    selection: dict[str, object] = Field(default_factory=dict)
    identity_fields: list[str] = Field(..., min_length=1, max_length=16)
    ingestion_mode: ConnectorIngestionMode = "json_snapshot"
    deletion_policy: ConnectorDeletionPolicy = "keep_deleted_documents"
    batch_size: int = Field(default=500, ge=1, le=5000)
    row_limit: int = Field(default=5000, ge=1, le=1000000)


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
    doc_type: str | None = None
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
