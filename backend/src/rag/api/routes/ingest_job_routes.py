"""Scoped ingestion job history and health summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_admin_user, require_csrf, require_current_user
from ...auth.document_access import can_read_document, can_write_document
from ...auth.permissions import can_read_document_metadata, is_global_admin
from ...core.config import settings
from ...query.http import ServiceRequestError
from ...query.qdrant import QdrantClient as RetrievalQdrantClient
from ...shared.contracts.clearance import can_access_clearance
from ...repositories.documents import DocumentRepository, get_document_repository
from ...repositories.document_postgres import PostgresDocumentRepository
from ...repositories.identity import UserRecord
from ...repositories.ingest_config import IngestConfigRepository, effective_ingest_config, get_ingest_config_repository
from ...schemas.ingest_jobs import (
    IngestJobCancelResponse,
    IngestJobItem,
    IngestJobListResponse,
    IngestJobOrigin,
    IngestJobRecoveryResponse,
    IngestJobSummaryResponse,
    StaleIngestJobItem,
    StaleIngestJobListResponse,
)
from ...services.ingest_queue import IngestQueue, get_ingest_queue
from ...services.ingest_recovery import (
    IngestRecoveryError,
    MAX_INGEST_ATTEMPTS,
    list_stale_ingest_jobs,
    requeue_stale_ingest_job,
)
from ...services.ingest_worker_control import IngestWorkerControl, WorkerControlResult, get_ingest_worker_control
from ...services.upload_status import build_job_status_response, stage_for_job_status


router = APIRouter(prefix="/ingest-jobs", tags=["ingest-jobs"])

JOB_STATUSES = {"scheduled", "queued", "processing", "complete", "failed", "human_review", "cancelled"}
JOB_ORIGINS = {"upload", "reingest", "restore", "folder", "unknown"}
ACTIVE_JOB_STATUSES = {"scheduled", "queued", "processing", "human_review"}
CANCELLABLE_JOB_STATUSES = {"scheduled", "queued", "processing", "human_review"}


@router.get("", response_model=IngestJobListResponse, summary="List visible ingestion jobs")
async def list_ingest_jobs(
    job_status: str | None = Query(default=None, alias="status"),
    origin: str | None = Query(default=None),
    group_path: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> IngestJobListResponse:
    status_filter = _job_status(job_status)
    origin_filter = _job_origin(origin)
    normalized_group = normalize_group_path(group_path) if group_path else None
    items = _visible_job_items(
        user,
        repo,
        status_filter=status_filter,
        origin_filter=origin_filter,
        group_path=normalized_group,
        search=search,
        created_from=created_from,
        created_to=created_to,
    )
    return IngestJobListResponse(items=items[offset:offset + limit], total=len(items), limit=limit, offset=offset)


@router.get("/summary", response_model=IngestJobSummaryResponse, summary="Summarize visible ingestion jobs")
async def summarize_ingest_jobs(
    group_path: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> IngestJobSummaryResponse:
    normalized_group = normalize_group_path(group_path) if group_path else None
    fast_summary = _postgres_ingest_job_summary(
        user,
        repo,
        group_path=normalized_group,
        created_from=created_from,
        created_to=created_to,
    )
    if fast_summary is not None:
        return fast_summary

    items = _visible_job_items(
        user,
        repo,
        group_path=normalized_group,
        created_from=created_from,
        created_to=created_to,
    )
    status_counts = _count_by(items, "status")
    return IngestJobSummaryResponse(
        total=len(items),
        active=sum(status_counts.get(value, 0) for value in ACTIVE_JOB_STATUSES),
        status_counts=status_counts,
        stage_counts=_count_by(items, "stage"),
        origin_counts=_count_by(items, "origin"),
    )


@router.post(
    "/{job_id}/cancel",
    response_model=IngestJobCancelResponse,
    summary="Cancel an active ingestion job",
)
async def cancel_ingest_job(
    job_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> IngestJobCancelResponse:
    require_csrf(request)
    job = repo.get_ingest_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
        )
    document = repo.get_document(job.doc_id, include_deleted=True)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "document_not_found", "message": "Ingested document was not found."},
        )
    if not can_write_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ingest_cancel_forbidden", "message": "User cannot cancel this ingestion job."},
        )
    if job.status not in CANCELLABLE_JOB_STATUSES:
        return IngestJobCancelResponse(
            job_id=job.id,
            status=job.status,  # type: ignore[arg-type]
            message=f"Job is already {job.status}.",
        )

    review_items_closed = repo.cancel_review_batch_for_job(job.id)
    updated = repo.update_ingest_job(
        job.id,
        status="cancelled",
        progress_pct=job.progress_pct,
        stage_progress=None,
        warnings=list(job.warnings),
        error_code=None,
        error_message_safe=None,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Ingestion job was not found."},
        )

    revoke_error = _revoke_queued_ingest_task(queue, job.id)
    vector_cleanup_error = _delete_document_vectors(document.id)
    repo.append_audit_event(
        event_type="ingest.cancelled",
        actor_id=user.id,
        target_type="ingest_job",
        target_id=job.id,
        payload={
            "doc_id": document.id,
            "status_before": job.status,
            "progress_pct": job.progress_pct,
            "review_items_closed": review_items_closed,
            "revoke_error": revoke_error,
            "vector_cleanup_error": vector_cleanup_error,
        },
    )
    return IngestJobCancelResponse(job_id=updated.id, status="cancelled", message="Ingestion job cancelled.")


@router.get(
    "/stale",
    response_model=StaleIngestJobListResponse,
    summary="List stale ingestion jobs eligible for admin recovery",
)
async def list_stale_jobs(
    user: UserRecord = Depends(require_admin_user),
    repo: DocumentRepository = Depends(get_document_repository),
    config_repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    control: IngestWorkerControl = Depends(get_ingest_worker_control),
) -> StaleIngestJobListResponse:
    _ = user
    config = effective_ingest_config(repo=config_repo)
    snapshot = _worker_snapshot(control, config.worker_concurrency)
    candidates = list_stale_ingest_jobs(
        document_repo=repo,
        active_job_ids=snapshot.active_job_ids,
        stale_after_seconds=settings.ingest_stale_after_seconds,
    )
    items = [
        StaleIngestJobItem(
            job_id=candidate.job.id,
            document_id=candidate.job.doc_id,
            document_title=candidate.document.title if candidate.document and candidate.document.title else candidate.job.doc_id,
            group_path=candidate.document.group_path if candidate.document else "Unavailable",
            clearance_level=candidate.document.clearance_level if candidate.document else "NATO_RESTRICTED",
            attempt_count=candidate.job.attempt_count,
            max_attempts=MAX_INGEST_ATTEMPTS,
            last_activity_at=candidate.last_activity_at,
            stale_for_seconds=candidate.stale_for_seconds,
            recoverable=candidate.recoverable,
            recovery_code=candidate.recovery_code,
            recovery_message=candidate.recovery_message,
        )
        for candidate in candidates
    ]
    return StaleIngestJobListResponse(
        items=items,
        total=len(items),
        recoverable=sum(1 for item in items if item.recoverable),
        stale_after_seconds=settings.ingest_stale_after_seconds,
    )


@router.post(
    "/{job_id}/requeue",
    response_model=IngestJobRecoveryResponse,
    summary="Requeue one recoverable stale ingestion job",
)
async def requeue_stale_job(
    job_id: str,
    user: UserRecord = Depends(require_admin_user),
    repo: DocumentRepository = Depends(get_document_repository),
    queue: IngestQueue = Depends(get_ingest_queue),
    config_repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    control: IngestWorkerControl = Depends(get_ingest_worker_control),
) -> IngestJobRecoveryResponse:
    config = effective_ingest_config(repo=config_repo)
    snapshot = _worker_snapshot(control, config.worker_concurrency)
    try:
        job = requeue_stale_ingest_job(
            document_repo=repo,
            queue=queue,
            job_id=job_id,
            active_job_ids=snapshot.active_job_ids,
            stale_after_seconds=settings.ingest_stale_after_seconds,
            actor_id=user.id,
            audit_event_type="admin.ingest.requeued",
        )
    except IngestRecoveryError as exc:
        response_status = status.HTTP_404_NOT_FOUND if exc.code == "job_not_found" else status.HTTP_409_CONFLICT
        raise HTTPException(
            status_code=response_status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return IngestJobRecoveryResponse(
        job_id=job.id,
        next_attempt=job.attempt_count + 1,
        message=f"Job requeued. The worker will start attempt {job.attempt_count + 1} of {MAX_INGEST_ATTEMPTS}.",
    )


def _postgres_ingest_job_summary(
    user: UserRecord,
    repo: DocumentRepository,
    *,
    group_path: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
) -> IngestJobSummaryResponse | None:
    if not isinstance(repo, PostgresDocumentRepository):
        return None
    if not can_read_document_metadata(user):
        return IngestJobSummaryResponse()

    clauses = ["1 = 1"]
    params: list[object] = []
    if group_path:
        clauses.append("document.group_path = %s")
        params.append(group_path)
    if not is_global_admin(user):
        visible_groups = sorted({normalize_group_path(path) for path in user.group_paths})
        if not visible_groups:
            return IngestJobSummaryResponse()
        clauses.append("document.group_path = ANY(%s::text[])")
        params.append(visible_groups)
    if created_from:
        clauses.append("job.created_at >= %s")
        params.append(created_from)
    if created_to:
        clauses.append("job.created_at <= %s")
        params.append(created_to)

    rows = repo._execute_all(
        f"""
        SELECT job.status, job.progress_pct, COALESCE(job.origin, 'unknown') AS origin, document.clearance_level
        FROM ingest_jobs job
        JOIN documents document ON document.id = job.doc_id
        WHERE {' AND '.join(clauses)}
        """,
        tuple(params),
    )
    status_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    origin_counts: dict[str, int] = {}
    total = 0
    for row in rows:
        if not can_access_clearance(user.clearance_level, str(row["clearance_level"])):
            continue
        status_value = str(row["status"])
        origin_value = str(row["origin"] if row["origin"] in JOB_ORIGINS else "unknown")
        stage_value = stage_for_job_status(status_value, int(row["progress_pct"]))
        total += 1
        status_counts[status_value] = status_counts.get(status_value, 0) + 1
        stage_counts[stage_value] = stage_counts.get(stage_value, 0) + 1
        origin_counts[origin_value] = origin_counts.get(origin_value, 0) + 1

    return IngestJobSummaryResponse(
        total=total,
        active=sum(status_counts.get(value, 0) for value in ACTIVE_JOB_STATUSES),
        status_counts=status_counts,
        stage_counts=stage_counts,
        origin_counts=origin_counts,
    )


def _visible_job_items(
    user: UserRecord,
    repo: DocumentRepository,
    *,
    status_filter: str | None = None,
    origin_filter: IngestJobOrigin | None = None,
    group_path: str | None = None,
    search: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> list[IngestJobItem]:
    query = (search or "").strip().lower()
    items: list[IngestJobItem] = []
    for job in repo.list_ingest_jobs():
        document = repo.get_document(job.doc_id, include_deleted=True)
        if document is None or not can_read_document(user, document):
            continue
        if status_filter and job.status != status_filter:
            continue
        if origin_filter and job.origin != origin_filter:
            continue
        if group_path and not _matches_group(document.group_path, group_path):
            continue
        if created_from and (job.created_at is None or job.created_at < created_from):
            continue
        if created_to and (job.created_at is None or job.created_at > created_to):
            continue
        if query and query not in " ".join((job.id, job.doc_id, document.title or "", document.group_path)).lower():
            continue
        status_payload = build_job_status_response(job)
        items.append(
            IngestJobItem(
                **status_payload.model_dump(),
                document_id=document.id,
                document_title=document.title or document.id,
                group_path=document.group_path,
                clearance_level=document.clearance_level,
                origin=cast(IngestJobOrigin, job.origin if job.origin in JOB_ORIGINS else "unknown"),
            )
        )
    return items


def _job_status(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in JOB_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_job_status", "message": "Unknown ingestion job status."},
        )
    return value


def _job_origin(value: str | None) -> IngestJobOrigin | None:
    if value is None:
        return None
    if value not in JOB_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_job_origin", "message": "Unknown ingestion job origin."},
        )
    return cast(IngestJobOrigin, value)


def _matches_group(candidate: str, group_path: str) -> bool:
    normalized = normalize_group_path(candidate)
    return normalized == group_path


def _count_by(items: list[IngestJobItem], field: Literal["status", "stage", "origin"]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(getattr(item, field))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _worker_snapshot(control: IngestWorkerControl, desired_concurrency: int) -> WorkerControlResult:
    try:
        return control.snapshot(desired_concurrency)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ingest_worker_status_unavailable",
                "message": "Worker activity could not be verified, so stale-job recovery is temporarily disabled.",
            },
        ) from exc


def _revoke_queued_ingest_task(queue: IngestQueue, job_id: str) -> str | None:
    cancel = getattr(queue, "cancel", None)
    if not callable(cancel):
        return "queue_cancel_unavailable"
    try:
        cancel(job_id)
    except RuntimeError as exc:
        return str(exc)[:300]
    return None


def _delete_document_vectors(doc_id: str) -> str | None:
    qdrant = RetrievalQdrantClient(
        base_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        timeout_seconds=settings.rag_http_timeout_seconds,
    )
    try:
        qdrant.delete_document_points(doc_id)
    except ServiceRequestError as exc:
        return exc.message[:300]
    return None
