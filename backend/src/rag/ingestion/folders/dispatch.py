"""Execute due folder schedules and enqueue their ingestion jobs."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import logging
from pathlib import PurePosixPath

from ...documents.models import DocumentRepository
from ...documents.storage import UploadStorage
from ...documents.upload_validation import (
    UploadRejected,
    default_title,
    is_supported_document_name,
    validated_document_type,
    validate_upload_size,
)
from ..contracts import IngestJobPayload
from .config import FolderIngestionConfig
from .models import (
    FolderRunItemRecord,
    FolderScheduleRecord,
    FolderScheduleRepository,
)
from .scheduling import next_recurring_window_after_current
from .sources import LocalFolderSource, MinioPrefixSource
from ..job_models import IngestJobRepository
from ..queue import IngestQueue

logger = logging.getLogger(__name__)


def dispatch_due_schedules(
    *,
    schedule_repo: FolderScheduleRepository,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
    minio_source: MinioPrefixSource,
    local_folder_source: LocalFolderSource | None = None,
    storage: UploadStorage | None = None,
    config: FolderIngestionConfig,
    now: datetime | None = None,
    limit: int = 20,
) -> list[str]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    dispatched: list[str] = []
    for schedule in schedule_repo.list_due_schedules(current, limit=limit):
        if schedule.source_type == "connector":
            schedule_repo.update_schedule_next_run(
                schedule.id,
                status="cancelled",
                last_run_at=current,
                next_run_at=None,
            )
            continue
        run = _active_run_for_schedule(
            schedule,
            schedule_repo=schedule_repo,
            current=current,
        )
        try:
            if schedule.source_type == "snapshot":
                _dispatch_snapshot(
                    schedule,
                    run.id,
                    schedule_repo=schedule_repo,
                    document_repo=document_repo,
                    job_repo=job_repo,
                    queue=queue,
                )
                next_run_at = None
                next_status = "complete"
            elif schedule.source_type == "local_folder":
                if local_folder_source is None:
                    raise RuntimeError(
                        "local folder dispatch requires a local source adapter"
                    )
                _dispatch_local_folder(
                    schedule,
                    run.id,
                    schedule_repo=schedule_repo,
                    document_repo=document_repo,
                    job_repo=job_repo,
                    queue=queue,
                    local_folder_source=local_folder_source,
                    storage=storage,
                    config=config,
                )
                next_run_at = (
                    next_recurring_window_after_current(
                        schedule.recurrence,
                        timezone_name=schedule.timezone,
                        default_timezone=config.default_timezone,
                        now=current,
                    )
                    if schedule.schedule_type == "recurring"
                    else None
                )
                next_status = (
                    "active" if schedule.schedule_type == "recurring" else "complete"
                )
            elif schedule.source_type == "minio_prefix":
                _dispatch_minio_prefix(
                    schedule,
                    run.id,
                    schedule_repo=schedule_repo,
                    document_repo=document_repo,
                    job_repo=job_repo,
                    queue=queue,
                    minio_source=minio_source,
                    config=config,
                )
                next_run_at = (
                    next_recurring_window_after_current(
                        schedule.recurrence,
                        timezone_name=schedule.timezone,
                        default_timezone=config.default_timezone,
                        now=current,
                    )
                    if schedule.schedule_type == "recurring"
                    else None
                )
                next_status = (
                    "active" if schedule.schedule_type == "recurring" else "complete"
                )
            else:
                raise RuntimeError(
                    f"unsupported folder schedule source type: {schedule.source_type}"
                )
            schedule_repo.update_run(run.id, status="complete", completed_at=current)
            schedule_repo.update_schedule_next_run(
                schedule.id,
                status=next_status,
                last_run_at=current,
                next_run_at=next_run_at,
            )
            dispatched.append(schedule.id)
        except Exception as exc:
            logger.exception(
                "Folder ingestion dispatch failed",
                extra={"folder_schedule_id": schedule.id},
            )
            schedule_repo.update_run(
                run.id,
                status="failed",
                completed_at=current,
                error_code="folder_dispatch_failed",
                error_message_safe=str(exc)[:500],
            )
            schedule_repo.update_schedule_next_run(
                schedule.id,
                status="failed",
                last_run_at=current,
                next_run_at=None,
            )
    return dispatched


def _active_run_for_schedule(
    schedule: FolderScheduleRecord,
    *,
    schedule_repo: FolderScheduleRepository,
    current: datetime,
):
    if schedule.source_type == "snapshot":
        for run in schedule_repo.list_runs(schedule.id):
            if run.status == "scheduled":
                updated = schedule_repo.update_run(
                    run.id,
                    status="running",
                    started_at=current,
                )
                return updated or run
    return schedule_repo.create_run(
        schedule_id=schedule.id,
        status="running",
        due_at=current,
        started_at=current,
    )


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
    _queue_pending_items(
        schedule,
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=job_repo,
        queue=queue,
    )


def _queue_pending_items(
    schedule: FolderScheduleRecord,
    *,
    schedule_repo: FolderScheduleRepository,
    document_repo: DocumentRepository,
    job_repo: IngestJobRepository,
    queue: IngestQueue,
) -> None:
    for item in schedule_repo.list_pending_items_for_schedule(schedule.id):
        _queue_item(
            schedule,
            item,
            document_repo=document_repo,
            job_repo=job_repo,
            schedule_repo=schedule_repo,
            queue=queue,
        )


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
    config: FolderIngestionConfig,
) -> None:
    if storage is None:
        raise RuntimeError("local folder dispatch requires upload storage")
    root_path = str(schedule.source_config.get("path") or "")
    if not root_path:
        raise RuntimeError("local folder schedule is missing a path")
    _queue_pending_items(
        schedule,
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=job_repo,
        queue=queue,
    )
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
                skip_message=("Only PDF, DOCX, JPG, PNG, and JSON files are accepted."),
            )
            continue
        if source_object.size_bytes > config.upload_max_bytes:
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
        content = local_folder_source.read_object(
            root_path=root_path,
            relative_path=source_object.source_path,
        )
        try:
            validate_upload_size(content, max_bytes=config.upload_max_bytes)
            content_type = validated_document_type(
                content,
                source_object.filename,
                None,
            )
        except UploadRejected as exc:
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                size_bytes=len(content),
                status="skipped",
                skip_code=exc.code,
                skip_message=exc.message,
            )
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        if schedule_repo.has_source_content(
            schedule.id,
            source_object.source_path,
            content_hash,
        ):
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
        previous = schedule_repo.latest_document_for_source(
            schedule.id,
            source_object.source_path,
        )
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
                skip_message=(
                    "A current document with the same content already exists."
                ),
            )
            continue
        stored = storage.put(
            filename=source_object.filename,
            content=content,
            content_type=content_type,
        )
        document = document_repo.create_document(
            title=source_object.filename or default_title(content_type),
            source_id=_source_id(
                schedule.id,
                source_object.source_path,
                content_hash,
            ),
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
        job = job_repo.create_ingest_job(
            doc_id=document.id,
            status="scheduled",
            progress_pct=0,
            origin="folder",
        )
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
        _queue_item(
            schedule,
            item,
            document_repo=document_repo,
            job_repo=job_repo,
            schedule_repo=schedule_repo,
            queue=queue,
            supersedes=supersedes,
        )

    for source_path in sorted(
        schedule_repo.known_source_paths(schedule.id) - seen_paths
    ):
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
    config: FolderIngestionConfig,
) -> None:
    _queue_pending_items(
        schedule,
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=job_repo,
        queue=queue,
    )
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
                skip_message=("Only PDF, DOCX, JPG, PNG, and JSON files are accepted."),
            )
            continue
        if source_object.size_bytes > config.upload_max_bytes:
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
        content = minio_source.read_object(
            bucket=source_object.bucket,
            object_name=source_object.object_name,
        )
        try:
            validate_upload_size(content, max_bytes=config.upload_max_bytes)
            content_type = validated_document_type(
                content,
                source_object.filename,
                None,
            )
        except UploadRejected as exc:
            schedule_repo.create_run_item(
                run_id=run_id,
                schedule_id=schedule.id,
                source_path=source_object.source_path,
                filename=source_object.filename,
                size_bytes=len(content),
                status="skipped",
                skip_code=exc.code,
                skip_message=exc.message,
            )
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        if schedule_repo.has_source_content(
            schedule.id,
            source_object.source_path,
            content_hash,
        ):
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
        previous = schedule_repo.latest_document_for_source(
            schedule.id,
            source_object.source_path,
        )
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
                skip_message=(
                    "A current document with the same content already exists."
                ),
            )
            continue
        document = document_repo.create_document(
            title=source_object.filename or default_title(content_type),
            source_id=_source_id(
                schedule.id,
                source_object.source_path,
                content_hash,
            ),
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
        job = job_repo.create_ingest_job(
            doc_id=document.id,
            status="scheduled",
            progress_pct=0,
            origin="folder",
        )
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
        _queue_item(
            schedule,
            item,
            document_repo=document_repo,
            job_repo=job_repo,
            schedule_repo=schedule_repo,
            queue=queue,
            supersedes=supersedes,
        )

    for source_path in sorted(
        schedule_repo.known_source_paths(schedule.id) - seen_paths
    ):
        schedule_repo.create_run_item(
            run_id=run_id,
            schedule_id=schedule.id,
            source_path=source_path,
            filename=PurePosixPath(source_path).name or source_path,
            status="skipped",
            skip_code="source_deleted",
            skip_message=(
                "Source object is no longer present in the configured prefix."
            ),
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
    if (
        not item.document_id
        or not item.job_id
        or not item.object_path
        or not item.content_type
    ):
        schedule_repo.update_run_item_status(
            item.id,
            status="failed",
            skip_code="missing_job",
            skip_message="Scheduled item is missing document or job metadata.",
        )
        return
    document = document_repo.get_document(item.document_id)
    if document is None:
        schedule_repo.update_run_item_status(
            item.id,
            status="failed",
            skip_code="document_not_found",
            skip_message="Scheduled document was not found.",
        )
        return
    job_repo.update_ingest_job(item.job_id, status="queued", progress_pct=0)
    try:
        queue.enqueue(
            IngestJobPayload(
                job_id=item.job_id,
                doc_id=item.document_id,
                file_path=item.object_path,
                group_path=schedule.group_path,
                acl_group_paths=list(document.access_group_paths),
                clearance_level=schedule.clearance_level,
                doc_type=schedule.doc_type,
                effective_date=(
                    schedule.effective_date.isoformat()
                    if schedule.effective_date
                    else None
                ),
                supersedes=(
                    supersedes
                    if supersedes is not None
                    else list(document.pending_supersedes)
                ),
                expiry_date=(
                    schedule.expiry_date.isoformat() if schedule.expiry_date else None
                ),
                description=schedule.description,
                content_type=item.content_type,
            )
        )
    except Exception:
        job_repo.update_ingest_job(
            item.job_id,
            status="scheduled",
            progress_pct=0,
            error_code="folder_enqueue_failed",
            error_message_safe="Folder ingestion queue was unavailable.",
        )
        schedule_repo.update_run_item_status(
            item.id,
            status="scheduled",
            skip_code="folder_enqueue_failed",
            skip_message="Folder ingestion queue was unavailable.",
            document_id=item.document_id,
            job_id=item.job_id,
        )
        raise
    schedule_repo.update_run_item_status(
        item.id,
        status="queued",
        skip_code=None,
        skip_message=None,
        document_id=item.document_id,
        job_id=item.job_id,
    )


def _source_id(schedule_id: str, source_path: str, content_hash: str) -> str:
    path_hash = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]
    return f"folder:{schedule_id}:{path_hash}:{content_hash}"
