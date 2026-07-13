"""Browser snapshot validation, staging, and schedule creation."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
from pathlib import PurePosixPath
from typing import Protocol

from ...auth.identity_models import IdentityRepository, UserRecord
from ...documents.models import DocumentRepository
from ...documents.scanning import FileScanner
from ...documents.storage import UploadStorage
from ...documents.upload_validation import (
    UploadRejected,
    default_title,
    is_supported_document_name,
    scan_upload,
    validated_document_type,
    validate_upload_size,
)
from ..job_models import IngestJobRepository
from .config import FolderIngestionConfig
from .errors import FolderIngestionRejected
from .models import FolderScheduleRecord, FolderScheduleRepository
from .schedule_access import (
    require_folder_schedule_clearance,
    require_folder_schedule_scope,
)
from .schedule_validation import _folder_rejection, _validated_schedule_metadata
from .scheduling import next_run_for_schedule, normalize_timezone


class SnapshotUpload(Protocol):
    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes: ...

    async def seek(self, offset: int) -> None: ...

async def create_snapshot_schedule(
    *,
    files: list[SnapshotUpload],
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
    config: FolderIngestionConfig,
) -> FolderScheduleRecord:
    normalized_group = require_folder_schedule_scope(user, group_path, identity_repo)
    normalized_clearance = require_folder_schedule_clearance(user, clearance_level)
    if schedule_type != "one_time":
        raise FolderIngestionRejected(
            category="invalid",
            code="snapshot_one_time_only",
            message="Browser folder snapshots support one-time scheduling only.",
        )
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
    if not files:
        raise FolderIngestionRejected(
            category="invalid",
            code="empty_folder",
            message="Selected folder does not contain supported files.",
        )
    if relative_paths and len(relative_paths) != len(files):
        raise FolderIngestionRejected(
            category="invalid",
            code="relative_path_mismatch",
            message="Each uploaded file must include one relative path.",
        )

    staged_skips: list[dict[str, object]] = []
    staged_accepts: list[tuple[SnapshotUpload, str, str, int, str, str]] = []
    accepted_hashes: set[str] = set()
    total_bytes = 0
    supported_candidates = 0

    for index, upload in enumerate(files):
        source_path = _safe_relative_path(
            relative_paths[index] if relative_paths else upload.filename
        )
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
        if supported_candidates > config.snapshot_max_files:
            raise FolderIngestionRejected(
                category="too_large",
                code="folder_file_limit",
                message=f"Folder snapshots cannot exceed {config.snapshot_max_files} supported files.",
            )
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > config.snapshot_max_bytes:
            staged_skips.append(
                {
                    "source_path": source_path,
                    "filename": filename,
                    "size_bytes": len(content),
                    "status": "skipped",
                    "skip_code": "folder_too_large",
                    "skip_message": f"Folder snapshots cannot exceed {_format_byte_limit(config.snapshot_max_bytes)} total.",
                }
            )
            continue
        try:
            validate_upload_size(content, max_bytes=config.upload_max_bytes)
            content_type = validated_document_type(
                content, filename, upload.content_type
            )
            scan_upload(scanner, content)
        except UploadRejected as exc:
            if exc.category == "unavailable":
                raise _folder_rejection(exc) from exc
            staged_skips.append(
                {
                    "source_path": source_path,
                    "filename": filename,
                    "size_bytes": len(content),
                    "status": "skipped",
                    "skip_code": exc.code,
                    "skip_message": exc.message,
                }
            )
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        if (
            content_hash in accepted_hashes
            or document_repo.find_current_by_content_hash(content_hash)
        ):
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
        staged_accepts.append(
            (upload, source_path, filename, len(content), content_type, content_hash)
        )

    if not staged_accepts:
        raise FolderIngestionRejected(
            category="invalid",
            code="empty_folder",
            message="Selected folder does not contain any accepted PDF, DOCX, JPG, PNG, or JSON files.",
        )

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
    run = schedule_repo.create_run(
        schedule_id=schedule.id, status="scheduled", due_at=next_run_at
    )

    for skipped in staged_skips:
        schedule_repo.create_run_item(run_id=run.id, schedule_id=schedule.id, **skipped)

    for (
        upload,
        source_path,
        filename,
        size_bytes,
        content_type,
        content_hash,
    ) in staged_accepts:
        await upload.seek(0)
        content = await upload.read()
        if (
            len(content) != size_bytes
            or hashlib.sha256(content).hexdigest() != content_hash
        ):
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
        stored = storage.put(
            filename=filename, content=content, content_type=content_type
        )
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
        job = job_repo.create_ingest_job(
            doc_id=document.id, status="scheduled", progress_pct=0, origin="folder"
        )
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
        payload={
            "source_type": "snapshot",
            "group_path": normalized_group,
            "clearance_level": normalized_clearance,
            "accepted_count": len(staged_accepts),
        },
    )
    return schedule

def _safe_relative_path(value: str | None) -> str:
    raw = (value or "").replace("\\", "/").strip("/")
    parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
    if not parts:
        raise FolderIngestionRejected(
            category="invalid",
            code="invalid_relative_path",
            message="Folder file path is invalid.",
        )
    return "/".join(parts)


def _source_id(schedule_id: str, source_path: str, content_hash: str) -> str:
    path_hash = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]
    return f"folder:{schedule_id}:{path_hash}:{content_hash}"


def _format_byte_limit(value: int) -> str:
    gibibyte = 1024 * 1024 * 1024
    if value >= gibibyte:
        return f"{value / gibibyte:g} GB"
    return f"{value / (1024 * 1024):g} MB"
