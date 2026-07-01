"""In-memory folder schedule repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..auth.abac import normalize_group_path
from ..shared.contracts.clearance import normalize_clearance_level
from .folder_schedule_models import FolderRunItemRecord, FolderRunRecord, FolderScheduleRecord


class InMemoryFolderScheduleRepository:
    def __init__(self) -> None:
        self._schedules: dict[str, FolderScheduleRecord] = {}
        self._runs: dict[str, FolderRunRecord] = {}
        self._items: dict[str, FolderRunItemRecord] = {}

    def create_schedule(self, **kwargs: Any) -> FolderScheduleRecord:
        now = datetime.now(UTC)
        record = FolderScheduleRecord(
            id=kwargs.get("schedule_id") or str(uuid4()),
            name=str(kwargs["name"]).strip(),
            source_type=str(kwargs["source_type"]),
            schedule_type=str(kwargs["schedule_type"]),
            status=str(kwargs["status"]),
            group_path=normalize_group_path(kwargs["group_path"]),
            clearance_level=normalize_clearance_level(kwargs.get("clearance_level")),
            doc_type=str(kwargs["doc_type"]) if kwargs.get("doc_type") else None,
            effective_date=kwargs["effective_date"],
            expiry_date=kwargs.get("expiry_date"),
            description=kwargs.get("description"),
            timezone=str(kwargs["timezone"]),
            scheduled_at=kwargs.get("scheduled_at"),
            recurrence=dict(kwargs.get("recurrence") or {}),
            source_config=dict(kwargs.get("source_config") or {}),
            created_by=kwargs.get("created_by"),
            last_run_at=None,
            next_run_at=kwargs.get("next_run_at"),
            created_at=now,
            updated_at=now,
        )
        self._schedules[record.id] = record
        return record

    def list_schedules(self) -> list[FolderScheduleRecord]:
        return sorted(self._schedules.values(), key=lambda schedule: schedule.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    def list_due_schedules(self, now: datetime, *, limit: int = 20) -> list[FolderScheduleRecord]:
        eligible = [
            schedule for schedule in self._schedules.values()
            if schedule.status in {"scheduled", "active"} and schedule.next_run_at and schedule.next_run_at <= now
        ]
        return sorted(eligible, key=lambda schedule: schedule.next_run_at or datetime.max.replace(tzinfo=UTC))[:limit]

    def get_schedule(self, schedule_id: str) -> FolderScheduleRecord | None:
        return self._schedules.get(schedule_id)

    def delete_schedule(self, schedule_id: str) -> FolderScheduleRecord | None:
        schedule = self._schedules.pop(schedule_id, None)
        if schedule is None:
            return None
        run_ids = {run.id for run in self._runs.values() if run.schedule_id == schedule_id}
        self._runs = {run_id: run for run_id, run in self._runs.items() if run.schedule_id != schedule_id}
        self._items = {
            item_id: item
            for item_id, item in self._items.items()
            if item.schedule_id != schedule_id and item.run_id not in run_ids
        }
        return schedule

    def update_schedule_status(self, schedule_id: str, *, status: str) -> FolderScheduleRecord | None:
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            return None
        updated = replace(schedule, status=status, updated_at=datetime.now(UTC))
        self._schedules[schedule_id] = updated
        return updated

    def update_schedule_next_run(
        self,
        schedule_id: str,
        *,
        status: str | None = None,
        last_run_at: datetime | None = None,
        next_run_at: datetime | None = None,
    ) -> FolderScheduleRecord | None:
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            return None
        updated = replace(
            schedule,
            status=status or schedule.status,
            last_run_at=last_run_at if last_run_at is not None else schedule.last_run_at,
            next_run_at=next_run_at,
            updated_at=datetime.now(UTC),
        )
        self._schedules[schedule_id] = updated
        return updated

    def reschedule(
        self,
        schedule_id: str,
        *,
        schedule_type: str,
        scheduled_at: datetime | None,
        recurrence: dict[str, Any],
        timezone: str,
        next_run_at: datetime | None,
    ) -> FolderScheduleRecord | None:
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            return None
        updated = replace(
            schedule,
            schedule_type=schedule_type,
            scheduled_at=scheduled_at,
            recurrence=dict(recurrence),
            timezone=timezone,
            next_run_at=next_run_at,
            status="active" if schedule_type == "recurring" else "scheduled",
            updated_at=datetime.now(UTC),
        )
        self._schedules[schedule_id] = updated
        return updated

    def create_run(self, *, schedule_id: str, status: str, due_at: datetime, started_at: datetime | None = None) -> FolderRunRecord:
        now = datetime.now(UTC)
        run = FolderRunRecord(
            id=str(uuid4()),
            schedule_id=schedule_id,
            status=status,
            due_at=due_at,
            started_at=started_at,
            completed_at=None,
            error_code=None,
            error_message_safe=None,
            created_at=now,
            updated_at=now,
        )
        self._runs[run.id] = run
        return run

    def update_run(self, run_id: str, **kwargs: Any) -> FolderRunRecord | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        updated = replace(run, updated_at=datetime.now(UTC), **kwargs)
        self._runs[run_id] = updated
        return updated

    def list_runs(self, schedule_id: str) -> list[FolderRunRecord]:
        runs = [run for run in self._runs.values() if run.schedule_id == schedule_id]
        return sorted(runs, key=lambda run: run.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    def get_run(self, run_id: str) -> FolderRunRecord | None:
        return self._runs.get(run_id)

    def create_run_item(self, **kwargs: Any) -> FolderRunItemRecord:
        now = datetime.now(UTC)
        item = FolderRunItemRecord(
            id=str(uuid4()),
            run_id=kwargs["run_id"],
            schedule_id=kwargs["schedule_id"],
            source_path=kwargs["source_path"],
            filename=kwargs["filename"],
            object_path=kwargs.get("object_path"),
            content_hash=kwargs.get("content_hash"),
            size_bytes=kwargs.get("size_bytes"),
            content_type=kwargs.get("content_type"),
            status=kwargs.get("status", "scheduled"),
            skip_code=kwargs.get("skip_code"),
            skip_message=kwargs.get("skip_message"),
            document_id=kwargs.get("document_id"),
            job_id=kwargs.get("job_id"),
            created_at=now,
            updated_at=now,
        )
        self._items[item.id] = item
        return item

    def update_run_item_status(self, item_id: str, **kwargs: Any) -> FolderRunItemRecord | None:
        item = self._items.get(item_id)
        if item is None:
            return None
        updated = replace(item, updated_at=datetime.now(UTC), **kwargs)
        self._items[item_id] = updated
        return updated

    def list_run_items(self, run_id: str) -> list[FolderRunItemRecord]:
        items = [item for item in self._items.values() if item.run_id == run_id]
        return sorted(items, key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC))

    def list_pending_items_for_schedule(self, schedule_id: str) -> list[FolderRunItemRecord]:
        items = [item for item in self._items.values() if item.schedule_id == schedule_id and item.status == "scheduled"]
        return sorted(items, key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC))

    def latest_document_for_source(self, schedule_id: str, source_path: str) -> tuple[str, str | None] | None:
        candidates = [
            item for item in self._items.values()
            if item.schedule_id == schedule_id and item.source_path == source_path and item.document_id and item.status in {"queued", "scheduled"}
        ]
        if not candidates:
            return None
        latest = sorted(candidates, key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)[0]
        return latest.document_id or "", latest.content_hash

    def has_source_content(self, schedule_id: str, source_path: str, content_hash: str) -> bool:
        return any(
            item.schedule_id == schedule_id and item.source_path == source_path and item.content_hash == content_hash and item.document_id
            for item in self._items.values()
        )

    def known_source_paths(self, schedule_id: str) -> set[str]:
        return {item.source_path for item in self._items.values() if item.schedule_id == schedule_id and item.document_id}
