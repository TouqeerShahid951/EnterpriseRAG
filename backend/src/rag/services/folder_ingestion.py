"""Scheduled folder ingestion staging and dispatch."""

from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from fastapi import HTTPException, UploadFile, status

from ..auth.abac import normalize_group_path
from ..auth.permissions import can_manage_group_path
from ..connectors.crypto import decrypt_secret, keyring_from_settings
from ..connectors.models import CONNECTOR_RECORD_CONTENT_TYPE, DIRECT_CHUNKS_MODE, JSON_SNAPSHOT_MODE
from ..connectors.repositories import ConnectorProfileRepository
from ..connectors.registry import ConnectorRegistry
from ..connectors.sql_safety import SqlValidationError, validate_read_only_sql
from ..core.config import settings
from ..repositories.document_models import DocumentRepository
from ..repositories.folder_schedule_models import FolderRunItemRecord, FolderScheduleRecord, FolderScheduleRepository
from ..repositories.identity import IdentityRepository, UserRecord
from ..repositories.ingest_job_models import IngestJobRepository
from ..shared.contracts.clearance import clearance_rank, normalize_clearance_level
from .document_uploads import (
    default_title,
    is_supported_document_name,
    scan_upload,
    validated_description,
    validated_document_type,
    validate_declared_dates,
    validate_upload_size,
)
from .file_scanning import FileScanner
from .folder_schedule_time import next_recurring_window_after_current, next_run_for_schedule, normalize_timezone
from .folder_sources import LocalFolderSource, MinioPrefixSource, resolve_local_folder_path
from ..ingestion.contracts import IngestJobPayload
from ..ingestion.queue import IngestQueue
from .upload_storage import UploadStorage

FOLDER_SNAPSHOT_MAX_FILES = settings.folder_snapshot_max_files
FOLDER_SNAPSHOT_MAX_BYTES = settings.folder_snapshot_max_bytes


def require_folder_schedule_scope(user: UserRecord, group_path: str, identity_repo: IdentityRepository) -> str:
    normalized = normalize_group_path(group_path)
    known = {group.path for group in identity_repo.list_groups()}
    if normalized not in known:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "group_not_found", "message": "Folder schedule group does not exist."},
        )
    if not can_manage_group_path(user, normalized):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "folder_schedule_forbidden", "message": "User cannot manage folder ingestion for this Knowledge Space."},
        )
    return normalized


def require_folder_schedule_clearance(user: UserRecord, clearance_level: str) -> str:
    try:
        normalized = normalize_clearance_level(clearance_level)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_clearance_level", "message": str(exc)},
        ) from exc
    if clearance_rank(normalized) > clearance_rank(user.clearance_level):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "folder_schedule_clearance_forbidden", "message": "User cannot schedule ingestion above their clearance level."},
        )
    return normalized


async def create_snapshot_schedule(
    *,
    files: list[UploadFile],
    relative_paths: list[str],
    name: str,
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
    job_repo: IngestJobRepository,
    schedule_repo: FolderScheduleRepository,
    storage: UploadStorage,
    scanner: FileScanner,
) -> FolderScheduleRecord:
    normalized_group = require_folder_schedule_scope(user, group_path, identity_repo)
    normalized_clearance = require_folder_schedule_clearance(user, clearance_level)
    if schedule_type != "one_time":
        raise HTTPException(
            status_code=400,
            detail={"code": "snapshot_one_time_only", "message": "Browser folder snapshots support one-time scheduling only."},
        )
    validate_declared_dates(effective_date, expiry_date)
    normalized_description = validated_description(description)
    normalized_timezone = normalize_timezone(timezone_name)
    next_run_at = next_run_for_schedule(
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        timezone_name=normalized_timezone,
    )
    if not files:
        raise HTTPException(status_code=400, detail={"code": "empty_folder", "message": "Selected folder does not contain supported files."})
    if relative_paths and len(relative_paths) != len(files):
        raise HTTPException(status_code=400, detail={"code": "relative_path_mismatch", "message": "Each uploaded file must include one relative path."})

    staged_skips: list[dict[str, object]] = []
    staged_accepts: list[tuple[UploadFile, str, str, int, str, str]] = []
    accepted_hashes: set[str] = set()
    total_bytes = 0
    supported_candidates = 0

    for index, upload in enumerate(files):
        source_path = _safe_relative_path(relative_paths[index] if relative_paths else upload.filename)
        filename = PurePosixPath(source_path).name or upload.filename or "upload.bin"
        if not is_supported_document_name(filename):
            staged_skips.append(
                {
                    "source_path": source_path,
                    "filename": filename,
                    "status": "skipped",
                    "skip_code": "unsupported_file_type",
                    "skip_message": "Only PDF, DOCX, JPG, PNG, and JSON files are accepted.",
                }
            )
            continue
        supported_candidates += 1
        if supported_candidates > FOLDER_SNAPSHOT_MAX_FILES:
            raise HTTPException(status_code=413, detail={"code": "folder_file_limit", "message": f"Folder snapshots cannot exceed {FOLDER_SNAPSHOT_MAX_FILES} supported files."})
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > FOLDER_SNAPSHOT_MAX_BYTES:
            staged_skips.append(
                {
                    "source_path": source_path,
                    "filename": filename,
                    "size_bytes": len(content),
                    "status": "skipped",
                    "skip_code": "folder_too_large",
                    "skip_message": f"Folder snapshots cannot exceed {_format_byte_limit(FOLDER_SNAPSHOT_MAX_BYTES)} total.",
                }
            )
            continue
        try:
            validate_upload_size(content)
            content_type = validated_document_type(content, filename, upload.content_type)
            scan_upload(scanner, content)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            staged_skips.append(
                {
                    "source_path": source_path,
                    "filename": filename,
                    "size_bytes": len(content),
                    "status": "skipped",
                    "skip_code": str(detail.get("code") or "file_rejected"),
                    "skip_message": str(detail.get("message") or "File rejected."),
                }
            )
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash in accepted_hashes or document_repo.find_current_by_content_hash(content_hash):
            staged_skips.append(
                {
                    "source_path": source_path,
                    "filename": filename,
                    "content_hash": content_hash,
                    "size_bytes": len(content),
                    "content_type": content_type,
                    "status": "skipped",
                    "skip_code": "duplicate_document",
                    "skip_message": "A current document with the same content already exists.",
                }
            )
            continue
        accepted_hashes.add(content_hash)
        staged_accepts.append((upload, source_path, filename, len(content), content_type, content_hash))

    if not staged_accepts:
        raise HTTPException(status_code=400, detail={"code": "empty_folder", "message": "Selected folder does not contain any accepted PDF, DOCX, JPG, PNG, or JSON files."})

    schedule = schedule_repo.create_schedule(
        name=name,
        source_type="snapshot",
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
        source_config={"mode": "browser_snapshot"},
        created_by=user.id,
        next_run_at=next_run_at,
    )
    run = schedule_repo.create_run(schedule_id=schedule.id, status="scheduled", due_at=next_run_at)

    for skipped in staged_skips:
        schedule_repo.create_run_item(run_id=run.id, schedule_id=schedule.id, **skipped)

    for upload, source_path, filename, size_bytes, content_type, content_hash in staged_accepts:
        await upload.seek(0)
        content = await upload.read()
        if len(content) != size_bytes or hashlib.sha256(content).hexdigest() != content_hash:
            schedule_repo.create_run_item(
                run_id=run.id,
                schedule_id=schedule.id,
                source_path=source_path,
                filename=filename,
                size_bytes=len(content),
                content_type=content_type,
                status="failed",
                skip_code="staged_file_changed",
                skip_message="Folder file changed while the snapshot was being staged.",
            )
            continue
        stored = storage.put(filename=filename, content=content, content_type=content_type)
        document = document_repo.create_document(
            title=filename or default_title(content_type),
            source_id=_source_id(schedule.id, source_path, content_hash),
            group_path=normalized_group,
            clearance_level=normalized_clearance,
            doc_type=doc_type,
            effective_date=effective_date,
            expiry_date=expiry_date,
            description=normalized_description,
            uploaded_by=user.id,
            file_path=stored.object_path,
            content_hash=content_hash,
            pending_supersedes=[],
            ingest_status="scheduled",
        )
        job = job_repo.create_ingest_job(doc_id=document.id, status="scheduled", progress_pct=0, origin="folder")
        schedule_repo.create_run_item(
            run_id=run.id,
            schedule_id=schedule.id,
            source_path=source_path,
            filename=filename,
            object_path=stored.object_path,
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            content_type=content_type,
            status="scheduled",
            document_id=document.id,
            job_id=job.id,
        )

    document_repo.append_audit_event(
        event_type="folder_ingest.schedule_created",
        actor_id=user.id,
        target_type="folder_schedule",
        target_id=schedule.id,
        payload={"source_type": "snapshot", "group_path": normalized_group, "clearance_level": normalized_clearance, "accepted_count": len(staged_accepts)},
    )
    return schedule


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
) -> FolderScheduleRecord:
    normalized_group = require_folder_schedule_scope(user, group_path, identity_repo)
    normalized_clearance = require_folder_schedule_clearance(user, clearance_level)
    validate_declared_dates(effective_date, expiry_date)
    normalized_description = validated_description(description)
    normalized_timezone = normalize_timezone(timezone_name)
    next_run_at = next_run_for_schedule(
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        timezone_name=normalized_timezone,
    )
    normalized_prefix = prefix.strip().lstrip("/")
    if not bucket.strip() or not normalized_prefix:
        raise HTTPException(status_code=400, detail={"code": "invalid_minio_source", "message": "Bucket and prefix are required."})
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
        payload={"source_type": "minio_prefix", "group_path": normalized_group, "clearance_level": normalized_clearance, "bucket": bucket.strip(), "prefix": normalized_prefix},
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
) -> FolderScheduleRecord:
    normalized_group = require_folder_schedule_scope(user, group_path, identity_repo)
    normalized_clearance = require_folder_schedule_clearance(user, clearance_level)
    validate_declared_dates(effective_date, expiry_date)
    normalized_description = validated_description(description)
    normalized_timezone = normalize_timezone(timezone_name)
    next_run_at = next_run_for_schedule(
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        timezone_name=normalized_timezone,
    )
    try:
        normalized_path = str(resolve_local_folder_path(path))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_local_folder_source", "message": str(exc)}) from exc
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
        payload={"source_type": "local_folder", "group_path": normalized_group, "clearance_level": normalized_clearance, "path": normalized_path},
    )
    return schedule


def create_connector_schedule(
    *,
    name: str,
    connector_profile_id: str,
    selection: dict[str, object],
    identity_fields: list[str],
    ingestion_mode: str,
    deletion_policy: str,
    batch_size: int,
    row_limit: int,
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
    connector_profile_repo: ConnectorProfileRepository,
) -> FolderScheduleRecord:
    _ = (
        name,
        connector_profile_id,
        selection,
        identity_fields,
        ingestion_mode,
        deletion_policy,
        batch_size,
        row_limit,
        group_path,
        clearance_level,
        effective_date,
        expiry_date,
        doc_type,
        description,
        schedule_type,
        timezone_name,
        scheduled_at,
        recurrence,
        user,
        identity_repo,
        document_repo,
        schedule_repo,
        connector_profile_repo,
    )
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "connector_schedules_retired",
            "message": "Database connector sync schedules are retired. Use approved schema catalogs for live read-only SQL.",
        },
    )


def dispatch_due_schedules(
    *,
    schedule_repo: FolderScheduleRepository,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
    minio_source: MinioPrefixSource,
    local_folder_source: LocalFolderSource | None = None,
    connector_profile_repo: ConnectorProfileRepository | None = None,
    connector_registry: ConnectorRegistry | None = None,
    storage: UploadStorage | None = None,
    qdrant: Any | None = None,
    now: datetime | None = None,
    limit: int = 20,
) -> list[str]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    dispatched: list[str] = []
    for schedule in schedule_repo.list_due_schedules(current, limit=limit):
        if schedule.source_type == "connector":
            schedule_repo.update_schedule_next_run(schedule.id, status="cancelled", last_run_at=current, next_run_at=None)
            continue
        run = _active_run_for_schedule(schedule, schedule_repo=schedule_repo, current=current)
        try:
            if schedule.source_type == "snapshot":
                _dispatch_snapshot(schedule, run.id, schedule_repo=schedule_repo, document_repo=document_repo, job_repo=job_repo, queue=queue)
                next_run_at = None
                next_status = "complete"
            elif schedule.source_type == "local_folder":
                _dispatch_local_folder(
                    schedule,
                    run.id,
                    schedule_repo=schedule_repo,
                    document_repo=document_repo,
                    job_repo=job_repo,
                    queue=queue,
                    local_folder_source=local_folder_source or LocalFolderSource(),
                    storage=storage,
                )
                next_run_at = (
                    next_recurring_window_after_current(schedule.recurrence, timezone_name=schedule.timezone, now=current)
                    if schedule.schedule_type == "recurring"
                    else None
                )
                next_status = "active" if schedule.schedule_type == "recurring" else "complete"
            else:
                _dispatch_minio_prefix(schedule, run.id, schedule_repo=schedule_repo, document_repo=document_repo, job_repo=job_repo, queue=queue, minio_source=minio_source)
                next_run_at = (
                    next_recurring_window_after_current(schedule.recurrence, timezone_name=schedule.timezone, now=current)
                    if schedule.schedule_type == "recurring"
                    else None
                )
                next_status = "active" if schedule.schedule_type == "recurring" else "complete"
            schedule_repo.update_run(run.id, status="complete", completed_at=current)
            schedule_repo.update_schedule_next_run(schedule.id, status=next_status, last_run_at=current, next_run_at=next_run_at)
            dispatched.append(schedule.id)
        except Exception as exc:
            schedule_repo.update_run(
                run.id,
                status="failed",
                completed_at=current,
                error_code="folder_dispatch_failed",
                error_message_safe=str(exc)[:500],
            )
            schedule_repo.update_schedule_next_run(schedule.id, status="failed", last_run_at=current, next_run_at=None)
    return dispatched


def _active_run_for_schedule(schedule: FolderScheduleRecord, *, schedule_repo: FolderScheduleRepository, current: datetime):
    if schedule.source_type == "snapshot":
        for run in schedule_repo.list_runs(schedule.id):
            if run.status == "scheduled":
                updated = schedule_repo.update_run(run.id, status="running", started_at=current)
                return updated or run
    return schedule_repo.create_run(schedule_id=schedule.id, status="running", due_at=current, started_at=current)


def _dispatch_snapshot(
    schedule: FolderScheduleRecord,
    run_id: str,
    *,
    schedule_repo: FolderScheduleRepository,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
) -> None:
    _ = run_id
    for item in schedule_repo.list_pending_items_for_schedule(schedule.id):
        _queue_item(schedule, item, document_repo=document_repo, job_repo=job_repo, schedule_repo=schedule_repo, queue=queue)


def _dispatch_local_folder(
    schedule: FolderScheduleRecord,
    run_id: str,
    *,
    schedule_repo: FolderScheduleRepository,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
    local_folder_source: LocalFolderSource,
    storage: UploadStorage | None,
) -> None:
    if storage is None:
        raise RuntimeError("local folder dispatch requires upload storage")
    root_path = str(schedule.source_config.get("path") or "")
    if not root_path:
        raise RuntimeError("local folder schedule is missing a path")
    seen_paths: set[str] = set()
    for source_object in local_folder_source.list_objects(root_path=root_path):
        seen_paths.add(source_object.source_path)
        if not is_supported_document_name(source_object.filename):
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                size_bytes=source_object.size_bytes,
                status="skipped",
                skip_code="unsupported_file_type",
                skip_message="Only PDF, DOCX, JPG, PNG, and JSON files are accepted.",
            )
            continue
        if source_object.size_bytes > settings.upload_max_bytes:
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                size_bytes=source_object.size_bytes,
                status="skipped",
                skip_code="upload_too_large",
                skip_message="Uploaded file exceeds the configured size limit.",
            )
            continue
        content = local_folder_source.read_object(root_path=root_path, relative_path=source_object.source_path)
        try:
            validate_upload_size(content)
            content_type = validated_document_type(content, source_object.filename, None)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                size_bytes=len(content),
                status="skipped",
                skip_code=str(detail.get("code") or "file_rejected"),
                skip_message=str(detail.get("message") or "File rejected."),
            )
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        if schedule_repo.has_source_content(schedule.id, source_object.source_path, content_hash):
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                content_hash=content_hash,
                size_bytes=len(content),
                content_type=content_type,
                status="skipped",
                skip_code="unchanged_source",
                skip_message="Source file has not changed since the last sync.",
            )
            continue
        previous = schedule_repo.latest_document_for_source(schedule.id, source_object.source_path)
        supersedes = [previous[0]] if previous else []
        duplicate = document_repo.find_current_by_content_hash(content_hash)
        if duplicate and not supersedes:
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                content_hash=content_hash,
                size_bytes=len(content),
                content_type=content_type,
                status="skipped",
                skip_code="duplicate_document",
                skip_message="A current document with the same content already exists.",
            )
            continue
        stored = storage.put(filename=source_object.filename, content=content, content_type=content_type)
        document = document_repo.create_document(
            title=source_object.filename or default_title(content_type),
            source_id=_source_id(schedule.id, source_object.source_path, content_hash),
            group_path=schedule.group_path,
            clearance_level=schedule.clearance_level,
            doc_type=schedule.doc_type,
            effective_date=schedule.effective_date,
            expiry_date=schedule.expiry_date,
            description=schedule.description,
            uploaded_by=schedule.created_by,
            file_path=stored.object_path,
            content_hash=content_hash,
            pending_supersedes=supersedes,
            ingest_status="scheduled",
        )
        job = job_repo.create_ingest_job(doc_id=document.id, status="scheduled", progress_pct=0, origin="folder")
        item = schedule_repo.create_run_item(
            run_id=run_id,
            schedule_id=schedule.id,
            source_path=source_object.source_path,
            filename=source_object.filename,
            object_path=stored.object_path,
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            content_type=content_type,
            status="scheduled",
            document_id=document.id,
            job_id=job.id,
        )
        _queue_item(schedule, item, document_repo=document_repo, job_repo=job_repo, schedule_repo=schedule_repo, queue=queue, supersedes=supersedes)

    for source_path in sorted(schedule_repo.known_source_paths(schedule.id) - seen_paths):
        schedule_repo.create_run_item(
            run_id=run_id,
            schedule_id=schedule.id,
            source_path=source_path,
            filename=PurePosixPath(source_path).name or source_path,
            status="skipped",
            skip_code="source_deleted",
            skip_message="Source file is no longer present in the watched folder.",
        )


def _dispatch_minio_prefix(
    schedule: FolderScheduleRecord,
    run_id: str,
    *,
    schedule_repo: FolderScheduleRepository,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
    minio_source: MinioPrefixSource,
) -> None:
    bucket = str(schedule.source_config.get("bucket") or "")
    prefix = str(schedule.source_config.get("prefix") or "")
    seen_paths: set[str] = set()
    for source_object in minio_source.list_objects(bucket=bucket, prefix=prefix):
        seen_paths.add(source_object.source_path)
        if not is_supported_document_name(source_object.filename):
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                size_bytes=source_object.size_bytes,
                status="skipped",
                skip_code="unsupported_file_type",
                skip_message="Only PDF, DOCX, JPG, PNG, and JSON files are accepted.",
            )
            continue
        if source_object.size_bytes > settings.upload_max_bytes:
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                size_bytes=source_object.size_bytes,
                status="skipped",
                skip_code="upload_too_large",
                skip_message="Uploaded file exceeds the configured size limit.",
            )
            continue
        content = minio_source.read_object(bucket=source_object.bucket, object_name=source_object.object_name)
        try:
            validate_upload_size(content)
            content_type = validated_document_type(content, source_object.filename, None)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                size_bytes=len(content),
                status="skipped",
                skip_code=str(detail.get("code") or "file_rejected"),
                skip_message=str(detail.get("message") or "File rejected."),
            )
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        if schedule_repo.has_source_content(schedule.id, source_object.source_path, content_hash):
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                content_hash=content_hash,
                size_bytes=len(content),
                content_type=content_type,
                status="skipped",
                skip_code="unchanged_source",
                skip_message="Source file has not changed since the last sync.",
            )
            continue
        previous = schedule_repo.latest_document_for_source(schedule.id, source_object.source_path)
        supersedes = [previous[0]] if previous else []
        duplicate = document_repo.find_current_by_content_hash(content_hash)
        if duplicate and not supersedes:
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                content_hash=content_hash,
                size_bytes=len(content),
                content_type=content_type,
                status="skipped",
                skip_code="duplicate_document",
                skip_message="A current document with the same content already exists.",
            )
            continue
        document = document_repo.create_document(
            title=source_object.filename or default_title(content_type),
            source_id=_source_id(schedule.id, source_object.source_path, content_hash),
            group_path=schedule.group_path,
            clearance_level=schedule.clearance_level,
            doc_type=schedule.doc_type,
            effective_date=schedule.effective_date,
            expiry_date=schedule.expiry_date,
            description=schedule.description,
            uploaded_by=schedule.created_by,
            file_path=source_object.object_path,
            content_hash=content_hash,
            pending_supersedes=supersedes,
            ingest_status="scheduled",
        )
        job = job_repo.create_ingest_job(doc_id=document.id, status="scheduled", progress_pct=0, origin="folder")
        item = schedule_repo.create_run_item(
            run_id=run_id,
            schedule_id=schedule.id,
            source_path=source_object.source_path,
            filename=source_object.filename,
            object_path=source_object.object_path,
            content_hash=content_hash,
            size_bytes=len(content),
            content_type=content_type,
            status="scheduled",
            document_id=document.id,
            job_id=job.id,
        )
        _queue_item(schedule, item, document_repo=document_repo, job_repo=job_repo, schedule_repo=schedule_repo, queue=queue, supersedes=supersedes)

    for source_path in sorted(schedule_repo.known_source_paths(schedule.id) - seen_paths):
        schedule_repo.create_run_item(
            run_id=run_id,
            schedule_id=schedule.id,
            source_path=source_path,
            filename=PurePosixPath(source_path).name or source_path,
            status="skipped",
            skip_code="source_deleted",
            skip_message="Source object is no longer present in the configured prefix.",
        )


def _dispatch_connector(
    schedule: FolderScheduleRecord,
    run_id: str,
    *,
    schedule_repo: FolderScheduleRepository,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
    connector_profile_repo: ConnectorProfileRepository | None,
    connector_registry: ConnectorRegistry,
    storage: UploadStorage | None,
    qdrant: Any | None,
) -> None:
    if connector_profile_repo is None or storage is None:
        raise RuntimeError("connector dispatch requires connector profile repository and upload storage")
    profile_id = str(schedule.source_config.get("connector_profile_id") or "")
    profile = connector_profile_repo.get_profile(profile_id)
    if profile is None:
        raise RuntimeError("connector profile was not found")
    selection = _object_config(schedule.source_config.get("selection"))
    identity_fields = _validated_identity_fields(_list_config(schedule.source_config.get("identity_fields")))
    ingestion_mode = _validated_ingestion_mode(str(schedule.source_config.get("ingestion_mode") or JSON_SNAPSHOT_MODE))
    deletion_policy = _validated_deletion_policy(str(schedule.source_config.get("deletion_policy") or "keep_deleted_documents"))
    batch_size = _bounded_int(schedule.source_config.get("batch_size"), default=settings.connector_default_batch_size, lower=1, upper=5000)
    row_limit = _bounded_int(schedule.source_config.get("row_limit"), default=settings.connector_default_row_limit, lower=1, upper=1000000)
    selection = {**selection, "row_limit": row_limit}
    connector = connector_registry.get(profile.connector_type)
    secrets = decrypt_secret(profile.encrypted_secrets, keyring_from_settings(settings.connector_secrets_key, settings.connector_secrets_key_ring))
    records = connector.iter_records(
        config=profile.public_config,
        secrets=secrets,
        selection=selection,
        identity_fields=identity_fields,
        batch_size=batch_size,
    )
    seen_paths: set[str] = set()
    for record in records[:row_limit]:
        seen_paths.add(record.source_path)
        content = _connector_record_bytes(schedule=schedule, profile=profile, record=record, ingestion_mode=ingestion_mode)
        content_hash = hashlib.sha256(content).hexdigest()
        content_type = CONNECTOR_RECORD_CONTENT_TYPE if ingestion_mode == DIRECT_CHUNKS_MODE else "application/json"
        if schedule_repo.has_source_content(schedule.id, record.source_path, content_hash):
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=record.source_path,
                filename=_connector_filename(record.source_path, ingestion_mode),
                content_hash=content_hash,
                size_bytes=len(content),
                content_type=content_type,
                status="skipped",
                skip_code="unchanged_source",
                skip_message="Source record has not changed since the last sync.",
            )
            continue
        previous = schedule_repo.latest_document_for_source(schedule.id, record.source_path)
        supersedes = [previous[0]] if previous else []
        duplicate = document_repo.find_current_by_content_hash(content_hash)
        if duplicate and not supersedes:
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=record.source_path,
                filename=_connector_filename(record.source_path, ingestion_mode),
                content_hash=content_hash,
                size_bytes=len(content),
                content_type=content_type,
                status="skipped",
                skip_code="duplicate_document",
                skip_message="A current document with the same connector record content already exists.",
            )
            continue
        stored = storage.put(filename=_connector_filename(record.source_path, ingestion_mode), content=content, content_type=content_type)
        document = document_repo.create_document(
            title=record.title,
            source_id=_connector_source_id(schedule.id, record.source_path, content_hash),
            group_path=schedule.group_path,
            clearance_level=schedule.clearance_level,
            doc_type=schedule.doc_type,
            effective_date=schedule.effective_date,
            expiry_date=schedule.expiry_date,
            description=schedule.description,
            uploaded_by=schedule.created_by,
            file_path=stored.object_path,
            content_hash=content_hash,
            pending_supersedes=supersedes,
            ingest_status="scheduled",
        )
        job = job_repo.create_ingest_job(doc_id=document.id, status="scheduled", progress_pct=0, origin="connector")
        item = schedule_repo.create_run_item(
            run_id=run_id,
            schedule_id=schedule.id,
            source_path=record.source_path,
            filename=_connector_filename(record.source_path, ingestion_mode),
            object_path=stored.object_path,
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            content_type=content_type,
            status="scheduled",
            document_id=document.id,
            job_id=job.id,
        )
        _queue_item(schedule, item, document_repo=document_repo, job_repo=job_repo, schedule_repo=schedule_repo, queue=queue, supersedes=supersedes)

    for source_path in sorted(schedule_repo.known_source_paths(schedule.id) - seen_paths):
        previous = schedule_repo.latest_document_for_source(schedule.id, source_path)
        if previous:
            _mark_connector_source_stale(
                document_repo=document_repo,
                qdrant=qdrant,
                document_id=previous[0],
                deletion_policy=deletion_policy,
            )
        schedule_repo.create_run_item(
            run_id=run_id,
            schedule_id=schedule.id,
            source_path=source_path,
            filename=_connector_filename(source_path, ingestion_mode),
            content_hash=previous[1] if previous else None,
            status="skipped",
            skip_code="source_deleted",
            skip_message="Source record is no longer present in the configured connector selection.",
            document_id=previous[0] if previous else None,
        )


def _queue_item(
    schedule: FolderScheduleRecord,
    item: FolderRunItemRecord,
    *,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    schedule_repo: FolderScheduleRepository,
    queue: IngestQueue,
    supersedes: list[str] | None = None,
) -> None:
    if not item.document_id or not item.job_id or not item.object_path or not item.content_type:
        schedule_repo.update_run_item_status(item.id, status="failed", skip_code="missing_job", skip_message="Scheduled item is missing document or job metadata.")
        return
    document = document_repo.get_document(item.document_id)
    if document is None:
        schedule_repo.update_run_item_status(item.id, status="failed", skip_code="document_not_found", skip_message="Scheduled document was not found.")
        return
    job_repo.update_ingest_job(item.job_id, status="queued", progress_pct=0)
    queue.enqueue(
        IngestJobPayload(
            job_id=item.job_id,
            doc_id=item.document_id,
            file_path=item.object_path,
            group_path=schedule.group_path,
            acl_group_paths=list(document.access_group_paths),
            clearance_level=schedule.clearance_level,
            doc_type=schedule.doc_type,
            effective_date=schedule.effective_date.isoformat() if schedule.effective_date else None,
            supersedes=supersedes if supersedes is not None else list(document.pending_supersedes),
            expiry_date=schedule.expiry_date.isoformat() if schedule.expiry_date else None,
            description=schedule.description,
            content_type=item.content_type,
        )
    )
    schedule_repo.update_run_item_status(item.id, status="queued", document_id=item.document_id, job_id=item.job_id)


def _safe_relative_path(value: str | None) -> str:
    raw = (value or "").replace("\\", "/").strip("/")
    parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
    if not parts:
        raise HTTPException(status_code=400, detail={"code": "invalid_relative_path", "message": "Folder file path is invalid."})
    return "/".join(parts)


def _source_id(schedule_id: str, source_path: str, content_hash: str) -> str:
    path_hash = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]
    return f"folder:{schedule_id}:{path_hash}:{content_hash}"


def _connector_source_id(schedule_id: str, source_path: str, content_hash: str) -> str:
    path_hash = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]
    return f"connector:{schedule_id}:{path_hash}:{content_hash}"


def _connector_record_bytes(*, schedule: FolderScheduleRecord, profile: Any, record: Any, ingestion_mode: str) -> bytes:
    envelope = {
        "source_type": "connector",
        "connector_type": profile.connector_type,
        "connector_profile_id": profile.id,
        "schedule_id": schedule.id,
        "source_path": record.source_path,
        "title": record.title,
        "identity": record.identity,
        "data": record.data,
        "ingestion_mode": ingestion_mode,
    }
    return json.dumps(envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def _connector_filename(source_path: str, ingestion_mode: str) -> str:
    suffix = ".connector.json" if ingestion_mode == DIRECT_CHUNKS_MODE else ".json"
    name = PurePosixPath(source_path).name or "connector-record"
    stem = name.rsplit(".", 1)[0] if "." in name else name
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in stem).strip("-")
    return f"{safe or 'connector-record'}{suffix}"


def _mark_connector_source_stale(*, document_repo: DocumentRepository, qdrant: Any | None, document_id: str, deletion_policy: str) -> None:
    reason = "source_deleted" if deletion_policy == "keep_deleted_documents" else deletion_policy
    updated = document_repo.mark_document_stale(document_id, source_deleted=True, retrieval_status="stale", reason=reason)
    if updated is not None and qdrant is not None and hasattr(qdrant, "set_document_retrieval_status"):
        qdrant.set_document_retrieval_status(document_id, retrieval_status="stale", source_deleted=True)


def _validated_identity_fields(identity_fields: list[Any]) -> list[str]:
    normalized = []
    for value in identity_fields:
        text = str(value).strip()
        if not text:
            continue
        normalized.append(text)
    if not normalized:
        raise HTTPException(status_code=400, detail={"code": "connector_identity_required", "message": "Connector schedules require at least one stable identity field."})
    return list(dict.fromkeys(normalized))


def _validated_connector_selection(connector_type: str, selection: dict[str, object], *, row_limit: int) -> dict[str, object]:
    normalized = dict(selection or {})
    normalized["row_limit"] = max(1, min(row_limit, 1000000))
    if connector_type in {"sql_server", "postgres", "mysql", "mariadb", "oracle"}:
        try:
            normalized["query"] = validate_read_only_sql(str(normalized.get("query") or ""), connector_type=connector_type)
        except SqlValidationError as exc:
            raise HTTPException(status_code=400, detail={"code": "unsafe_connector_query", "message": str(exc)}) from exc
    return normalized


def _validated_ingestion_mode(value: str) -> str:
    if value in {JSON_SNAPSHOT_MODE, DIRECT_CHUNKS_MODE}:
        return value
    raise HTTPException(status_code=400, detail={"code": "invalid_connector_ingestion_mode", "message": "Connector ingestion mode is invalid."})


def _validated_deletion_policy(value: str) -> str:
    if value in {"keep_deleted_documents", "mark_as_stale", "archive_from_retrieval", "delete_from_index_after_review"}:
        return value
    raise HTTPException(status_code=400, detail={"code": "invalid_connector_deletion_policy", "message": "Connector deletion policy is invalid."})


def _object_config(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _list_config(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _bounded_int(value: object, *, default: int, lower: int, upper: int) -> int:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        candidate = default
    return max(lower, min(candidate, upper))


def _format_byte_limit(value: int) -> str:
    gibibyte = 1024 * 1024 * 1024
    if value >= gibibyte:
        return f"{value / gibibyte:g} GB"
    return f"{value / (1024 * 1024):g} MB"
