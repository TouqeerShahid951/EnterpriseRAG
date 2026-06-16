"""Timezone-aware folder schedule calculations."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status

from ..core.config import settings

DEFAULT_WORKSPACE_TIMEZONE = settings.workspace_timezone


def normalize_timezone(value: str | None) -> str:
    candidate = (value or DEFAULT_WORKSPACE_TIMEZONE).strip() or DEFAULT_WORKSPACE_TIMEZONE
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_timezone", "message": f"Unknown timezone: {candidate}"},
        ) from exc
    return candidate


def next_run_for_schedule(
    *,
    schedule_type: str,
    scheduled_at: datetime | None,
    recurrence: dict[str, object] | None,
    timezone_name: str,
    now: datetime | None = None,
) -> datetime:
    now_utc = _as_utc(now or datetime.now(UTC))
    if schedule_type == "one_time":
        if scheduled_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "scheduled_at_required", "message": "A one-time schedule requires scheduled_at."},
            )
        return _as_utc(scheduled_at, timezone_name=timezone_name)
    if schedule_type != "recurring":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_schedule_type", "message": "Schedule type must be one_time or recurring."},
        )
    return next_recurring_window(recurrence or {}, timezone_name=timezone_name, now=now_utc)


def next_recurring_window(recurrence: dict[str, object], *, timezone_name: str, now: datetime | None = None) -> datetime:
    timezone = ZoneInfo(normalize_timezone(timezone_name))
    now_utc = _as_utc(now or datetime.now(UTC))
    local_now = now_utc.astimezone(timezone)
    days = _days_of_week(recurrence.get("days_of_week"))
    start = _parse_hhmm(str(recurrence.get("start_time") or ""))
    end = _parse_hhmm(str(recurrence.get("end_time") or ""))

    if _within_window(local_now, days=days, start=start, end=end):
        return now_utc

    for offset in range(0, 15):
        candidate_date = (local_now + timedelta(days=offset)).date()
        if candidate_date.weekday() not in days:
            continue
        candidate = datetime.combine(candidate_date, start, tzinfo=timezone)
        if candidate >= local_now:
            return candidate.astimezone(UTC)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "invalid_recurrence", "message": "Unable to calculate the next recurring schedule window."},
    )


def next_recurring_window_after_current(recurrence: dict[str, object], *, timezone_name: str, now: datetime | None = None) -> datetime:
    timezone = ZoneInfo(normalize_timezone(timezone_name))
    now_utc = _as_utc(now or datetime.now(UTC))
    local_now = now_utc.astimezone(timezone)
    days = _days_of_week(recurrence.get("days_of_week"))
    start = _parse_hhmm(str(recurrence.get("start_time") or ""))
    end = _parse_hhmm(str(recurrence.get("end_time") or ""))
    candidate_now = _current_window_end(local_now, days=days, start=start, end=end)
    if candidate_now is not None:
        return next_recurring_window(recurrence, timezone_name=timezone_name, now=candidate_now.astimezone(UTC))
    return next_recurring_window(recurrence, timezone_name=timezone_name, now=now_utc + timedelta(seconds=1))


def _within_window(local_now: datetime, *, days: set[int], start: time, end: time) -> bool:
    today = local_now.date()
    today_start = datetime.combine(today, start, tzinfo=local_now.tzinfo)
    today_end = datetime.combine(today, end, tzinfo=local_now.tzinfo)
    if end <= start:
        today_end += timedelta(days=1)
        yesterday = today - timedelta(days=1)
        yesterday_start = datetime.combine(yesterday, start, tzinfo=local_now.tzinfo)
        yesterday_end = datetime.combine(today, end, tzinfo=local_now.tzinfo)
        if yesterday.weekday() in days and yesterday_start <= local_now < yesterday_end:
            return True
    return today.weekday() in days and today_start <= local_now < today_end


def _current_window_end(local_now: datetime, *, days: set[int], start: time, end: time) -> datetime | None:
    today = local_now.date()
    today_start = datetime.combine(today, start, tzinfo=local_now.tzinfo)
    today_end = datetime.combine(today, end, tzinfo=local_now.tzinfo)
    if end <= start:
        today_end += timedelta(days=1)
        yesterday = today - timedelta(days=1)
        yesterday_start = datetime.combine(yesterday, start, tzinfo=local_now.tzinfo)
        yesterday_end = datetime.combine(today, end, tzinfo=local_now.tzinfo)
        if yesterday.weekday() in days and yesterday_start <= local_now < yesterday_end:
            return yesterday_end
    if today.weekday() in days and today_start <= local_now < today_end:
        return today_end
    return None


def _days_of_week(value: object) -> set[int]:
    if not isinstance(value, list) or not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_recurrence", "message": "Recurring schedules require at least one day of week."},
        )
    try:
        days = {int(item) for item in value}
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_recurrence", "message": "Recurring days must be integers from 0 to 6."},
        ) from exc
    if any(day < 0 or day > 6 for day in days):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_recurrence", "message": "Recurring days must be integers from 0 to 6."},
        )
    return days


def _parse_hhmm(value: str) -> time:
    try:
        hour, minute = value.split(":", 1)
        parsed = time(hour=int(hour), minute=int(minute))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_recurrence", "message": "Recurring start and end times must use HH:MM."},
        ) from exc
    return parsed


def _as_utc(value: datetime, *, timezone_name: str | None = None) -> datetime:
    if value.tzinfo is None:
        timezone = ZoneInfo(normalize_timezone(timezone_name)) if timezone_name else UTC
        return value.replace(tzinfo=timezone).astimezone(UTC)
    return value.astimezone(UTC)
