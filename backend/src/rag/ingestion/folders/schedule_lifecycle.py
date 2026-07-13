"""Lifecycle transitions for existing folder-ingestion schedules."""

from __future__ import annotations

from datetime import datetime

from .config import FolderIngestionConfig
from .errors import FolderIngestionRejected
from .models import FolderScheduleRecord, FolderScheduleRepository
from .schedule_access import require_visible_schedule
from .scheduling import next_run_for_schedule, normalize_timezone
from ...auth.identity_models import UserRecord


def reschedule_schedule(
    *,
    user: UserRecord,
    schedule_repo: FolderScheduleRepository,
    schedule_id: str,
    schedule_type: str,
    scheduled_at: datetime | None,
    recurrence: dict[str, object],
    timezone_name: str,
    config: FolderIngestionConfig,
) -> FolderScheduleRecord:
    schedule = require_visible_schedule(user, schedule_repo, schedule_id)
    normalized_timezone = normalize_timezone(
        timezone_name,
        default_timezone=config.default_timezone,
    )
    next_run_at = next_run_for_schedule(
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        timezone_name=normalized_timezone,
        default_timezone=config.default_timezone,
    )
    updated = schedule_repo.reschedule(
        schedule.id,
        schedule_type=schedule_type,
        scheduled_at=next_run_at if schedule_type == "one_time" else None,
        recurrence=recurrence,
        timezone=normalized_timezone,
        next_run_at=next_run_at,
    )
    return _require_schedule_write(updated)


def pause_schedule(
    *,
    user: UserRecord,
    schedule_repo: FolderScheduleRepository,
    schedule_id: str,
) -> FolderScheduleRecord:
    schedule = require_visible_schedule(user, schedule_repo, schedule_id)
    return _require_schedule_write(
        schedule_repo.update_schedule_status(schedule.id, status="paused")
    )


def resume_schedule(
    *,
    user: UserRecord,
    schedule_repo: FolderScheduleRepository,
    schedule_id: str,
    config: FolderIngestionConfig,
) -> FolderScheduleRecord:
    schedule = require_visible_schedule(user, schedule_repo, schedule_id)
    normalized_timezone = normalize_timezone(
        schedule.timezone,
        default_timezone=config.default_timezone,
    )
    next_run_at = next_run_for_schedule(
        schedule_type=schedule.schedule_type,
        scheduled_at=schedule.scheduled_at,
        recurrence=schedule.recurrence,
        timezone_name=normalized_timezone,
        default_timezone=config.default_timezone,
    )
    status_value = "active" if schedule.schedule_type == "recurring" else "scheduled"
    return _require_schedule_write(
        schedule_repo.update_schedule_next_run(
            schedule.id,
            status=status_value,
            next_run_at=next_run_at,
        )
    )


def cancel_schedule(
    *,
    user: UserRecord,
    schedule_repo: FolderScheduleRepository,
    schedule_id: str,
) -> FolderScheduleRecord:
    schedule = require_visible_schedule(user, schedule_repo, schedule_id)
    return _require_schedule_write(
        schedule_repo.update_schedule_next_run(
            schedule.id,
            status="cancelled",
            next_run_at=None,
        )
    )


def _require_schedule_write(
    schedule: FolderScheduleRecord | None,
) -> FolderScheduleRecord:
    if schedule is None:
        raise FolderIngestionRejected(
            category="not_found",
            code="schedule_not_found",
            message="Folder schedule was not found.",
        )
    return schedule
