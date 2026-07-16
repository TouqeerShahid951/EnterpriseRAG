"""Schedule creation for deployment-managed folder sources."""

from __future__ import annotations

from datetime import date, datetime

from ...auth.identity_models import IdentityRepository, UserRecord
from ...documents.models import DocumentRepository
from .config import FolderIngestionConfig
from .errors import FolderIngestionRejected
from .models import FolderScheduleRecord, FolderScheduleRepository
from .schedule_access import (
    require_folder_schedule_clearance,
    require_folder_schedule_scope,
)
from .schedule_validation import _validated_schedule_metadata
from .scheduling import next_run_for_schedule, normalize_timezone
from rag.ingestion.folders.sources import LocalFolderSource


def create_minio_prefix_schedule(
    *,
    name: str,
    bucket: str,
    prefix: str,
    group_path: str,
    clearance_level: str,
    effective_date: date | None,
    expiry_date: date | None,
    doc_type: str | None,
    description: str | None,
    schedule_type: str,
    timezone_name: str,
    scheduled_at: datetime | None,
    recurrence: dict[str, object],
    user: UserRecord,
    identity_repo: IdentityRepository,
    document_repo: DocumentRepository,
    schedule_repo: FolderScheduleRepository,
    config: FolderIngestionConfig,
) -> FolderScheduleRecord:
    normalized_group = require_folder_schedule_scope(user, group_path, identity_repo)
    normalized_clearance = require_folder_schedule_clearance(user, clearance_level)
    normalized_description = _validated_schedule_metadata(
        effective_date=effective_date,
        expiry_date=expiry_date,
        description=description,
    )
    normalized_timezone = normalize_timezone(
        timezone_name, default_timezone=config.default_timezone
    )
    next_run_at = next_run_for_schedule(
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        timezone_name=normalized_timezone,
        default_timezone=config.default_timezone,
    )
    normalized_prefix = prefix.strip().lstrip("/")
    if not bucket.strip() or not normalized_prefix:
        raise FolderIngestionRejected(
            category="invalid",
            code="invalid_minio_source",
            message="Bucket and prefix are required.",
        )
    schedule = schedule_repo.create_schedule(
        name=name,
        source_type="minio_prefix",
        schedule_type=schedule_type,
        status="active" if schedule_type == "recurring" else "scheduled",
        group_path=normalized_group,
        clearance_level=normalized_clearance,
        doc_type=doc_type,
        effective_date=effective_date,
        expiry_date=expiry_date,
        description=normalized_description,
        timezone=normalized_timezone,
        scheduled_at=next_run_at if schedule_type == "one_time" else None,
        recurrence=recurrence,
        source_config={"bucket": bucket.strip(), "prefix": normalized_prefix},
        created_by=user.id,
        next_run_at=next_run_at,
    )
    document_repo.append_audit_event(
        event_type="folder_ingest.schedule_created",
        actor_id=user.id,
        target_type="folder_schedule",
        target_id=schedule.id,
        payload={
            "source_type": "minio_prefix",
            "group_path": normalized_group,
            "clearance_level": normalized_clearance,
            "bucket": bucket.strip(),
            "prefix": normalized_prefix,
        },
    )
    return schedule


def create_local_folder_schedule(
    *,
    name: str,
    path: str,
    group_path: str,
    clearance_level: str,
    effective_date: date | None,
    expiry_date: date | None,
    doc_type: str | None,
    description: str | None,
    schedule_type: str,
    timezone_name: str,
    scheduled_at: datetime | None,
    recurrence: dict[str, object],
    user: UserRecord,
    identity_repo: IdentityRepository,
    document_repo: DocumentRepository,
    schedule_repo: FolderScheduleRepository,
    local_folder_source: LocalFolderSource,
    config: FolderIngestionConfig,
) -> FolderScheduleRecord:
    normalized_group = require_folder_schedule_scope(user, group_path, identity_repo)
    normalized_clearance = require_folder_schedule_clearance(user, clearance_level)
    normalized_description = _validated_schedule_metadata(
        effective_date=effective_date,
        expiry_date=expiry_date,
        description=description,
    )
    normalized_timezone = normalize_timezone(
        timezone_name, default_timezone=config.default_timezone
    )
    next_run_at = next_run_for_schedule(
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        timezone_name=normalized_timezone,
        default_timezone=config.default_timezone,
    )
    try:
        normalized_path = local_folder_source.resolve_root_path(path)
    except RuntimeError as exc:
        raise FolderIngestionRejected(
            category="invalid",
            code="invalid_local_folder_source",
            message=str(exc),
        ) from exc
    schedule = schedule_repo.create_schedule(
        name=name,
        source_type="local_folder",
        schedule_type=schedule_type,
        status="active" if schedule_type == "recurring" else "scheduled",
        group_path=normalized_group,
        clearance_level=normalized_clearance,
        doc_type=doc_type,
        effective_date=effective_date,
        expiry_date=expiry_date,
        description=normalized_description,
        timezone=normalized_timezone,
        scheduled_at=next_run_at if schedule_type == "one_time" else None,
        recurrence=recurrence,
        source_config={"path": normalized_path},
        created_by=user.id,
        next_run_at=next_run_at,
    )
    document_repo.append_audit_event(
        event_type="folder_ingest.schedule_created",
        actor_id=user.id,
        target_type="folder_schedule",
        target_id=schedule.id,
        payload={
            "source_type": "local_folder",
            "group_path": normalized_group,
            "clearance_level": normalized_clearance,
            "path": normalized_path,
        },
    )
    return schedule
