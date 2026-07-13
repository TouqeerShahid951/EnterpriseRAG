"""Pure behavior tests for folder-ingestion schedule calculations."""

from datetime import UTC, datetime

import pytest

from rag.ingestion.folders.errors import FolderIngestionRejected
from rag.ingestion.folders.scheduling import (
    next_recurring_window,
    next_recurring_window_after_current,
    next_run_for_schedule,
    normalize_timezone,
)


def test_one_time_schedule_interprets_naive_timestamp_in_workspace_timezone() -> None:
    next_run = next_run_for_schedule(
        schedule_type="one_time",
        scheduled_at=datetime(2026, 7, 13, 9, 30),
        recurrence=None,
        timezone_name="Asia/Karachi",
        default_timezone="UTC",
    )

    assert next_run == datetime(2026, 7, 13, 4, 30, tzinfo=UTC)


def test_normalize_timezone_rejects_unknown_timezone() -> None:
    with pytest.raises(FolderIngestionRejected) as raised:
        normalize_timezone("Mars/Olympus", default_timezone="UTC")

    assert raised.value.category == "invalid"
    assert raised.value.code == "invalid_timezone"


def test_recurring_window_returns_current_time_during_overnight_window() -> None:
    now = datetime(2026, 7, 14, 0, 30, tzinfo=UTC)

    next_run = next_recurring_window(
        {
            "days_of_week": [0],
            "start_time": "22:00",
            "end_time": "02:00",
        },
        timezone_name="UTC",
        default_timezone="UTC",
        now=now,
    )

    assert next_run == now


def test_recurring_window_returns_next_configured_start() -> None:
    next_run = next_recurring_window(
        {
            "days_of_week": [0, 2],
            "start_time": "09:00",
            "end_time": "17:00",
        },
        timezone_name="UTC",
        default_timezone="UTC",
        now=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )

    assert next_run == datetime(2026, 7, 15, 9, 0, tzinfo=UTC)


def test_next_window_after_current_skips_active_recurring_window() -> None:
    next_run = next_recurring_window_after_current(
        {
            "days_of_week": [0],
            "start_time": "09:00",
            "end_time": "17:00",
        },
        timezone_name="UTC",
        default_timezone="UTC",
        now=datetime(2026, 7, 13, 10, 0, tzinfo=UTC),
    )

    assert next_run == datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


def test_blank_timezone_uses_injected_workspace_default() -> None:
    next_run = next_run_for_schedule(
        schedule_type="one_time",
        scheduled_at=datetime(2030, 1, 1, 10, 0),
        recurrence=None,
        timezone_name="",
        default_timezone="America/New_York",
    )

    assert next_run == datetime(2030, 1, 1, 15, 0, tzinfo=UTC)
