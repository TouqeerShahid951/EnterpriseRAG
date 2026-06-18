"""Folder ingestion schedule repository contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class FolderScheduleRecord:
    id: str
    name: str
    source_type: str
    schedule_type: str
    status: str
    group_path: str
    clearance_level: str
    doc_type: str | None
    effective_date: date | None
    expiry_date: date | None
    description: str | None
    timezone: str
    scheduled_at: datetime | None
    recurrence: dict[str, Any]
    source_config: dict[str, Any]
    created_by: str | None
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class FolderRunRecord:
    id: str
    schedule_id: str
    status: str
    due_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message_safe: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class FolderRunItemRecord:
    id: str
    run_id: str
    schedule_id: str
    source_path: str
    filename: str
    object_path: str | None
    content_hash: str | None
    size_bytes: int | None
    content_type: str | None
    status: str
    skip_code: str | None
    skip_message: str | None
    document_id: str | None
    job_id: str | None
    created_at: datetime | None
    updated_at: datetime | None


class FolderScheduleRepository(Protocol):
    def create_schedule(self, **kwargs: Any) -> FolderScheduleRecord: ...
    def list_schedules(self) -> list[FolderScheduleRecord]: ...
    def list_due_schedules(self, now: datetime, *, limit: int = 20) -> list[FolderScheduleRecord]: ...
    def get_schedule(self, schedule_id: str) -> FolderScheduleRecord | None: ...
    def update_schedule_status(self, schedule_id: str, *, status: str) -> FolderScheduleRecord | None: ...
    def update_schedule_next_run(
        self,
        schedule_id: str,
        *,
        status: str | None = None,
        last_run_at: datetime | None = None,
        next_run_at: datetime | None = None,
    ) -> FolderScheduleRecord | None: ...
    def reschedule(
        self,
        schedule_id: str,
        *,
        schedule_type: str,
        scheduled_at: datetime | None,
        recurrence: dict[str, Any],
        timezone: str,
        next_run_at: datetime | None,
    ) -> FolderScheduleRecord | None: ...
    def create_run(self, *, schedule_id: str, status: str, due_at: datetime, started_at: datetime | None = None) -> FolderRunRecord: ...
    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
    ) -> FolderRunRecord | None: ...
    def list_runs(self, schedule_id: str) -> list[FolderRunRecord]: ...
    def get_run(self, run_id: str) -> FolderRunRecord | None: ...
    def create_run_item(self, **kwargs: Any) -> FolderRunItemRecord: ...
    def update_run_item_status(
        self,
        item_id: str,
        *,
        status: str,
        document_id: str | None = None,
        job_id: str | None = None,
        skip_code: str | None = None,
        skip_message: str | None = None,
    ) -> FolderRunItemRecord | None: ...
    def list_run_items(self, run_id: str) -> list[FolderRunItemRecord]: ...
    def list_pending_items_for_schedule(self, schedule_id: str) -> list[FolderRunItemRecord]: ...
    def latest_document_for_source(self, schedule_id: str, source_path: str) -> tuple[str, str | None] | None: ...
    def has_source_content(self, schedule_id: str, source_path: str, content_hash: str) -> bool: ...
    def known_source_paths(self, schedule_id: str) -> set[str]: ...
