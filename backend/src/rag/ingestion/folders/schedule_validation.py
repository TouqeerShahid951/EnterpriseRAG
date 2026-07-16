"""Shared metadata validation for folder-ingestion schedules."""

from __future__ import annotations

from datetime import date

from ...documents.upload.validation import (
    UploadRejected,
    validated_description,
    validate_declared_dates,
)
from .errors import FolderIngestionRejected


def _validated_schedule_metadata(
    *,
    effective_date: date | None,
    expiry_date: date | None,
    description: str | None,
) -> str | None:
    try:
        validate_declared_dates(effective_date, expiry_date)
        return validated_description(description)
    except UploadRejected as exc:
        raise _folder_rejection(exc) from exc


def _folder_rejection(exc: UploadRejected) -> FolderIngestionRejected:
    category = exc.category
    if category == "conflict":
        category = "invalid"
    return FolderIngestionRejected(
        category=category,
        code=exc.code,
        message=exc.message,
    )
