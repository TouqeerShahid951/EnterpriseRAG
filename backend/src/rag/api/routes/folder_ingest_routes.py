"""Scheduled folder ingestion routes."""

from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import ValidationError

from ...auth.dependencies import require_csrf, require_current_user
from ...auth.permissions import can_manage_group_path, can_manage_spaces, filter_group_paths_for_user, is_global_admin
from ...core.config import settings
from ...connectors.repositories import ConnectorProfileRepository, get_connector_profile_repository
from ...shared.contracts.clearance import can_access_clearance
from ...repositories.documents import DocumentRepository, get_document_repository
from ...repositories.folder_schedule_models import FolderRunItemRecord, FolderRunRecord, FolderScheduleRecord, FolderScheduleRepository
from ...repositories.folder_schedules import get_folder_schedule_repository
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...repositories.ingest_job_models import IngestJobRepository
from ...repositories.ingest_jobs import get_ingest_job_repository
from ...schemas.folder_ingest import (
    FolderRun,
    FolderRunItem,
    FolderRunItemListResponse,
    FolderRunListResponse,
    FolderSchedule,
    FolderScheduleActionResponse,
    FolderScheduleListResponse,
    FolderScheduleUpdateRequest,
    ConnectorScheduleCreateRequest,
    LocalFolderListResponse,
    LocalFolderScheduleCreateRequest,
    MinioPrefixScheduleCreateRequest,
    RecurrenceWindow,
)
from ...services.file_scanning import FileScanner, get_file_scanner
from ...services.folder_ingestion import create_local_folder_schedule, create_minio_prefix_schedule, create_snapshot_schedule
from ...services.folder_sources import list_local_folder_directories
from ...services.folder_schedule_time import next_run_for_schedule
from ...services.upload_storage import UploadStorage, get_upload_storage

router = APIRouter(prefix="/folder-ingest", tags=["folder-ingest"])


@router.get("/local-folders", response_model=LocalFolderListResponse, summary="List mounted local folder directories")
async def list_local_folders(
    path: str | None = None,
    user: UserRecord = Depends(require_current_user),
) -> LocalFolderListResponse:
    _require_schedule_admin(user)
    try:
        root, current, parent, items = list_local_folder_directories(root_path=settings.folder_sources_root, current_path=path)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_local_folder_path", "message": str(exc)}) from exc
    return LocalFolderListResponse(
        root_path=str(root),
        current_path=str(current),
        parent_path=str(parent) if parent else None,
        items=[{"name": item.name, "path": item.path, "has_children": item.has_children} for item in items],
    )


@router.get("/schedules", response_model=FolderScheduleListResponse, summary="List visible folder ingestion schedules")
async def list_folder_schedules(
    user: UserRecord = Depends(require_current_user),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderScheduleListResponse:
    _require_schedule_admin(user)
    schedules = [_schedule_to_schema(schedule, schedule_repo=schedule_repo) for schedule in _visible_schedules(user, schedule_repo.list_schedules())]
    return FolderScheduleListResponse(items=schedules, total=len(schedules))


@router.get("/schedules/{schedule_id}", response_model=FolderSchedule, summary="Read a folder ingestion schedule")
async def get_folder_schedule(
    schedule_id: str,
    user: UserRecord = Depends(require_current_user),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderSchedule:
    schedule = _require_visible_schedule(user, schedule_repo, schedule_id)
    return _schedule_to_schema(schedule, schedule_repo=schedule_repo)


@router.post("/schedules/snapshot", status_code=status.HTTP_202_ACCEPTED, response_model=FolderSchedule, summary="Schedule a browser folder snapshot")
async def create_snapshot_folder_schedule(
    request: Request,
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(default_factory=list),
    name: str = Form(...),
    group_path: str = Form(...),
    clearance_level: str = Form(default="NATO_RESTRICTED"),
    effective_date: date | None = Form(default=None),
    expiry_date: date | None = Form(default=None),
    doc_type: str | None = Form(default=None),
    description: str | None = Form(default=None),
    schedule_type: str = Form(...),
    timezone: str = Form(default="Asia/Karachi"),
    scheduled_at: datetime | None = Form(default=None),
    recurrence_json: str = Form(default="{}"),
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
    storage: UploadStorage = Depends(get_upload_storage),
    scanner: FileScanner = Depends(get_file_scanner),
) -> FolderSchedule:
    require_csrf(request)
    recurrence = _parse_recurrence(recurrence_json, schedule_type)
    schedule = await create_snapshot_schedule(
        files=files,
        relative_paths=relative_paths,
        name=name,
        group_path=group_path,
        clearance_level=clearance_level,
        effective_date=effective_date,
        expiry_date=expiry_date,
        doc_type=_normalize_declared_doc_type(doc_type),
        description=description,
        schedule_type=schedule_type,
        timezone_name=timezone,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        user=user,
        identity_repo=identity_repo,
        document_repo=document_repo,
        job_repo=job_repo,
        schedule_repo=schedule_repo,
        storage=storage,
        scanner=scanner,
    )
    return _schedule_to_schema(schedule, schedule_repo=schedule_repo)


@router.post("/schedules/minio-prefix", status_code=status.HTTP_202_ACCEPTED, response_model=FolderSchedule, summary="Schedule a MinIO prefix sync")
async def create_minio_folder_schedule(
    request: Request,
    payload: MinioPrefixScheduleCreateRequest,
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    document_repo: DocumentRepository = Depends(get_document_repository),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderSchedule:
    require_csrf(request)
    schedule = create_minio_prefix_schedule(
        name=payload.name,
        bucket=payload.bucket,
        prefix=payload.prefix,
        group_path=payload.group_path,
        clearance_level=payload.clearance_level,
        effective_date=payload.effective_date,
        expiry_date=payload.expiry_date,
        doc_type=_normalize_declared_doc_type(payload.doc_type),
        description=payload.description,
        schedule_type=payload.schedule_type,
        timezone_name=payload.timezone,
        scheduled_at=payload.scheduled_at,
        recurrence=payload.recurrence.model_dump() if payload.recurrence else {},
        user=user,
        identity_repo=identity_repo,
        document_repo=document_repo,
        schedule_repo=schedule_repo,
    )
    return _schedule_to_schema(schedule, schedule_repo=schedule_repo)


@router.post("/schedules/local-folder", status_code=status.HTTP_202_ACCEPTED, response_model=FolderSchedule, summary="Schedule a watched local folder sync")
async def create_local_folder_schedule_route(
    request: Request,
    payload: LocalFolderScheduleCreateRequest,
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    document_repo: DocumentRepository = Depends(get_document_repository),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderSchedule:
    require_csrf(request)
    schedule = create_local_folder_schedule(
        name=payload.name,
        path=payload.path,
        group_path=payload.group_path,
        clearance_level=payload.clearance_level,
        effective_date=payload.effective_date,
        expiry_date=payload.expiry_date,
        doc_type=_normalize_declared_doc_type(payload.doc_type),
        description=payload.description,
        schedule_type=payload.schedule_type,
        timezone_name=payload.timezone,
        scheduled_at=payload.scheduled_at,
        recurrence=payload.recurrence.model_dump() if payload.recurrence else {},
        user=user,
        identity_repo=identity_repo,
        document_repo=document_repo,
        schedule_repo=schedule_repo,
    )
    return _schedule_to_schema(schedule, schedule_repo=schedule_repo)


@router.post("/schedules/connector", status_code=status.HTTP_410_GONE, summary="Database connector sync schedules are retired")
async def create_connector_folder_schedule(
    request: Request,
    payload: ConnectorScheduleCreateRequest,
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    document_repo: DocumentRepository = Depends(get_document_repository),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
    connector_profile_repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
) -> None:
    _ = payload, user, identity_repo, document_repo, schedule_repo, connector_profile_repo
    require_csrf(request)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "connector_schedules_retired",
            "message": "Database connector sync schedules are retired. Use approved schema catalogs for live read-only SQL.",
        },
    )


@router.patch("/schedules/{schedule_id}", response_model=FolderSchedule, summary="Reschedule a folder ingestion schedule")
async def reschedule_folder_schedule(
    schedule_id: str,
    request: Request,
    payload: FolderScheduleUpdateRequest,
    user: UserRecord = Depends(require_current_user),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderSchedule:
    require_csrf(request)
    schedule = _require_visible_schedule(user, schedule_repo, schedule_id)
    next_run_at = next_run_for_schedule(
        schedule_type=payload.schedule_type,
        scheduled_at=payload.scheduled_at,
        recurrence=payload.recurrence.model_dump() if payload.recurrence else {},
        timezone_name=payload.timezone,
    )
    updated = schedule_repo.reschedule(
        schedule.id,
        schedule_type=payload.schedule_type,
        scheduled_at=next_run_at if payload.schedule_type == "one_time" else None,
        recurrence=payload.recurrence.model_dump() if payload.recurrence else {},
        timezone=payload.timezone,
        next_run_at=next_run_at,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "schedule_not_found", "message": "Folder schedule was not found."})
    return _schedule_to_schema(updated, schedule_repo=schedule_repo)


@router.post("/schedules/{schedule_id}/pause", response_model=FolderScheduleActionResponse, summary="Pause a folder ingestion schedule")
async def pause_folder_schedule(
    schedule_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderScheduleActionResponse:
    require_csrf(request)
    schedule = _require_visible_schedule(user, schedule_repo, schedule_id)
    updated = schedule_repo.update_schedule_status(schedule.id, status="paused")
    return FolderScheduleActionResponse(id=schedule.id, status=updated.status if updated else "paused")


@router.post("/schedules/{schedule_id}/resume", response_model=FolderScheduleActionResponse, summary="Resume a folder ingestion schedule")
async def resume_folder_schedule(
    schedule_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderScheduleActionResponse:
    require_csrf(request)
    schedule = _require_visible_schedule(user, schedule_repo, schedule_id)
    next_run_at = next_run_for_schedule(
        schedule_type=schedule.schedule_type,
        scheduled_at=schedule.scheduled_at,
        recurrence=schedule.recurrence,
        timezone_name=schedule.timezone,
    )
    status_value = "active" if schedule.schedule_type == "recurring" else "scheduled"
    updated = schedule_repo.update_schedule_next_run(schedule.id, status=status_value, next_run_at=next_run_at)
    return FolderScheduleActionResponse(id=schedule.id, status=updated.status if updated else status_value)


@router.post("/schedules/{schedule_id}/cancel", response_model=FolderScheduleActionResponse, summary="Cancel a folder ingestion schedule")
async def cancel_folder_schedule(
    schedule_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderScheduleActionResponse:
    require_csrf(request)
    schedule = _require_visible_schedule(user, schedule_repo, schedule_id)
    updated = schedule_repo.update_schedule_next_run(schedule.id, status="cancelled", next_run_at=None)
    return FolderScheduleActionResponse(id=schedule.id, status=updated.status if updated else "cancelled")


@router.get("/schedules/{schedule_id}/runs", response_model=FolderRunListResponse, summary="List folder ingestion schedule runs")
async def list_folder_runs(
    schedule_id: str,
    user: UserRecord = Depends(require_current_user),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderRunListResponse:
    schedule = _require_visible_schedule(user, schedule_repo, schedule_id)
    runs = [_run_to_schema(run, schedule_repo=schedule_repo) for run in schedule_repo.list_runs(schedule.id)]
    return FolderRunListResponse(items=runs, total=len(runs))


@router.get("/runs/{run_id}/items", response_model=FolderRunItemListResponse, summary="List folder ingestion run items")
async def list_folder_run_items(
    run_id: str,
    user: UserRecord = Depends(require_current_user),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
) -> FolderRunItemListResponse:
    run = schedule_repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": "Folder ingestion run was not found."})
    _require_visible_schedule(user, schedule_repo, run.schedule_id)
    items = [_item_to_schema(item) for item in schedule_repo.list_run_items(run.id)]
    return FolderRunItemListResponse(items=items, total=len(items))


def _require_schedule_admin(user: UserRecord) -> None:
    if not can_manage_spaces(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "folder_schedule_admin_required", "message": "Folder ingestion scheduling requires a platform or space admin."},
        )


def _visible_schedules(user: UserRecord, schedules: list[FolderScheduleRecord]) -> list[FolderScheduleRecord]:
    _require_schedule_admin(user)
    if is_global_admin(user):
        return [schedule for schedule in schedules if can_access_clearance(user.clearance_level, schedule.clearance_level)]
    visible_paths = set(filter_group_paths_for_user(user, [schedule.group_path for schedule in schedules]))
    return [
        schedule
        for schedule in schedules
        if schedule.group_path in visible_paths and can_access_clearance(user.clearance_level, schedule.clearance_level)
    ]


def _require_visible_schedule(user: UserRecord, repo: FolderScheduleRepository, schedule_id: str) -> FolderScheduleRecord:
    _require_schedule_admin(user)
    schedule = repo.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail={"code": "schedule_not_found", "message": "Folder schedule was not found."})
    if not can_manage_group_path(user, schedule.group_path) or not can_access_clearance(user.clearance_level, schedule.clearance_level):
        raise HTTPException(status_code=403, detail={"code": "folder_schedule_forbidden", "message": "Folder schedule is outside this user's Knowledge Space scope."})
    return schedule


def _parse_recurrence(value: str, schedule_type: str) -> dict[str, Any]:
    if schedule_type != "recurring":
        return {}
    try:
        raw = json.loads(value or "{}")
        recurrence = RecurrenceWindow.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_recurrence", "message": "Recurring schedule details are invalid."}) from exc
    return recurrence.model_dump()


def _normalize_declared_doc_type(value: str | None) -> str | None:
    normalized = " ".join((value or "").strip().lower().split())
    return normalized[:80] or None


def _schedule_to_schema(schedule: FolderScheduleRecord, *, schedule_repo: FolderScheduleRepository) -> FolderSchedule:
    latest_run = next(iter(schedule_repo.list_runs(schedule.id)), None)
    return FolderSchedule(
        id=schedule.id,
        name=schedule.name,
        source_type=schedule.source_type,
        schedule_type=schedule.schedule_type,
        status=schedule.status,
        group_path=schedule.group_path,
        clearance_level=schedule.clearance_level,
        doc_type=schedule.doc_type,
        effective_date=schedule.effective_date,
        expiry_date=schedule.expiry_date,
        description=schedule.description,
        timezone=schedule.timezone,
        scheduled_at=schedule.scheduled_at,
        recurrence=dict(schedule.recurrence),
        source_config=_public_source_config(schedule),
        created_by=schedule.created_by,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
        latest_run=_run_to_schema(latest_run, schedule_repo=schedule_repo) if latest_run else None,
    )


def _run_to_schema(run: FolderRunRecord, *, schedule_repo: FolderScheduleRepository) -> FolderRun:
    items = schedule_repo.list_run_items(run.id)
    return FolderRun(
        id=run.id,
        schedule_id=run.schedule_id,
        status=run.status,
        due_at=run.due_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_code=run.error_code,
        error_message=run.error_message_safe,
        created_at=run.created_at,
        updated_at=run.updated_at,
        item_count=len(items),
        queued_count=sum(1 for item in items if item.status == "queued"),
        skipped_count=sum(1 for item in items if item.status == "skipped"),
        failed_count=sum(1 for item in items if item.status == "failed"),
    )


def _item_to_schema(item: FolderRunItemRecord) -> FolderRunItem:
    return FolderRunItem(
        id=item.id,
        run_id=item.run_id,
        schedule_id=item.schedule_id,
        source_path=item.source_path,
        filename=item.filename,
        content_hash=item.content_hash,
        size_bytes=item.size_bytes,
        content_type=item.content_type,
        status=item.status,
        skip_code=item.skip_code,
        skip_message=item.skip_message,
        document_id=item.document_id,
        job_id=item.job_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _public_source_config(schedule: FolderScheduleRecord) -> dict[str, object]:
    if schedule.source_type == "local_folder":
        return {
            "path": str(schedule.source_config.get("path") or ""),
        }
    if schedule.source_type == "minio_prefix":
        return {
            "bucket": str(schedule.source_config.get("bucket") or ""),
            "prefix": str(schedule.source_config.get("prefix") or ""),
        }
    if schedule.source_type == "connector":
        return {
            "connector_profile_id": str(schedule.source_config.get("connector_profile_id") or ""),
            "connector_type": str(schedule.source_config.get("connector_type") or ""),
            "selection": dict(schedule.source_config.get("selection") or {}),
            "identity_fields": list(schedule.source_config.get("identity_fields") or []),
            "ingestion_mode": str(schedule.source_config.get("ingestion_mode") or "json_snapshot"),
            "deletion_policy": str(schedule.source_config.get("deletion_policy") or "keep_deleted_documents"),
            "batch_size": int(schedule.source_config.get("batch_size") or 500),
            "row_limit": int(schedule.source_config.get("row_limit") or 5000),
        }
    return {"mode": "browser_snapshot"}
