"""Scoped ingestion job history and health summaries."""

from __future__ import annotations

from datetime import datetime, timezone
import base64
import json
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_admin_user, require_csrf, require_current_user
from ...auth.document_access import can_read_document, can_write_document
from ...auth.permissions import can_read_document_metadata, is_global_admin
from ...core.config import settings
from ...query.http import ServiceRequestError
from ...query.qdrant import QdrantClient as RetrievalQdrantClient
from ...shared.contracts.clearance import ClearanceLevel, clearance_levels_at_or_below
from ...repositories.documents import DocumentRepository, get_document_repository
from ...repositories.document_postgres import PostgresDocumentRepository, job_from_row
from ...repositories.identity import UserRecord
from ...repositories.ingest_config import IngestConfigRepository, effective_ingest_config, get_ingest_config_repository
from ...schemas.common import ErrorResponse
from ...schemas.ingest_jobs import (
    GraphRAGActiveTask,
    GraphRAGCancelRequest,
    GraphRAGCancelResponse,
    GraphRAGQueuedTask,
    GraphRAGStatusResponse,
    GraphRAGWorkerState,
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
from ...services.graphrag_queue import GraphRAGMaintenanceQueue, get_graphrag_maintenance_queue
from ...services.ingest_recovery import (
    IngestRecoveryError,
    MAX_INGEST_ATTEMPTS,
    list_stale_ingest_jobs,
    requeue_stale_ingest_job,
)
from ...services.ingest_worker_control import (
    IngestWorkerControl,
    WorkerControlResult,
    get_graphrag_worker_control,
    get_ingest_worker_control,
)
from ...services.upload_status import build_job_status_response, stage_for_job_status


router = APIRouter(prefix="/ingest-jobs", tags=["ingest-jobs"])

JOB_STATUSES = {"scheduled", "queued", "processing", "complete", "failed", "human_review", "cancelled"}
JOB_ORIGINS = {"upload", "reingest", "restore", "folder", "connector", "unknown"}
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
    fast_response = _postgres_visible_job_response(
        user,
        repo,
        status_filter=status_filter,
        origin_filter=origin_filter,
        group_path=normalized_group,
        search=search,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    if fast_response is not None:
        return fast_response
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


@router.get(
    "/graphrag-status",
    response_model=GraphRAGStatusResponse,
    summary="Show GraphRAG queue and worker activity",
)
async def get_graphrag_status(
    user: UserRecord = Depends(require_current_user),
    control: IngestWorkerControl = Depends(get_graphrag_worker_control),
) -> GraphRAGStatusResponse:
    if not can_read_document_metadata(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "graphrag_status_forbidden", "message": "User cannot view ingestion health."},
        )
    snapshot, worker_error = _graphrag_worker_snapshot(control)
    queued_jobs, queue_error = _redis_queue_length(settings.graphrag_queue_name)
    queued_tasks = _redis_queued_graphrag_tasks(settings.graphrag_queue_name)
    now = datetime.now(timezone.utc)
    return GraphRAGStatusResponse(
        enabled=settings.graphrag_enabled,
        queue_name=settings.graphrag_queue_name,
        queued_jobs=queued_jobs,
        queue_error=queue_error,
        worker_online=bool(snapshot and snapshot.worker_online),
        worker_error=worker_error,
        active_jobs=snapshot.active_jobs if snapshot else 0,
        observed_pool_size=snapshot.observed_pool_size if snapshot else 0,
        workers=[
            GraphRAGWorkerState(name=worker.name, pool_size=worker.pool_size, active_jobs=worker.active_jobs)
            for worker in (snapshot.workers if snapshot else ())
        ],
        active_tasks=[
            _graphrag_active_task_response(task, now)
            for task in (snapshot.active_tasks if snapshot else ())
        ],
        queued_tasks=queued_tasks,
    )


@router.post(
    "/{job_id}/graph-enrichment/cancel",
    response_model=GraphRAGCancelResponse,
    responses={
        status.HTTP_200_OK: {"model": GraphRAGCancelResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    summary="Cancel queued or running graph enrichment",
)
async def cancel_graph_enrichment(
    job_id: str,
    payload: GraphRAGCancelRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    control: IngestWorkerControl = Depends(get_graphrag_worker_control),
    queue: GraphRAGMaintenanceQueue = Depends(get_graphrag_maintenance_queue),
) -> GraphRAGCancelResponse:
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
            detail={"code": "graphrag_cancel_forbidden", "message": "User cannot cancel graph enrichment for this document."},
        )
    snapshot, worker_error = _graphrag_worker_snapshot(control)
    active_tasks = [
        _graphrag_active_task_response(task, datetime.now(timezone.utc))
        for task in (snapshot.active_tasks if snapshot else ())
    ]
    queued_tasks = _redis_queued_graphrag_tasks(settings.graphrag_queue_name)
    active_task = next(
        (task for task in active_tasks if _cancel_task_matches(task, payload.task_id, job_id=job.id, document_id=document.id)),
        None,
    )
    queued_task = next(
        (task for task in queued_tasks if _cancel_task_matches(task, payload.task_id, job_id=job.id, document_id=document.id)),
        None,
    )
    if active_task is None and queued_task is None:
        _, queue_error = _redis_queue_length(settings.graphrag_queue_name)
        if worker_error and queue_error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "graphrag_status_unavailable", "message": "Graph task activity could not be verified."},
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "graphrag_task_not_active", "message": "Graph enrichment is no longer queued or running."},
        )
    terminate = active_task is not None
    try:
        queue.cancel(payload.task_id, terminate=terminate)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "graphrag_cancel_failed", "message": "Graph enrichment could not be cancelled."},
        ) from exc
    repo.append_audit_event(
        event_type="documents.graph_enrichment.cancelled",
        actor_id=user.id,
        target_type="document",
        target_id=document.id,
        payload={"job_id": job.id, "task_id": payload.task_id, "was_running": terminate},
    )
    return GraphRAGCancelResponse(
        task_id=payload.task_id,
        job_id=job.id,
        document_id=document.id,
        message="Running graph enrichment cancelled." if terminate else "Queued graph enrichment cancelled.",
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
    filter_result = _postgres_ingest_job_filters(
        user,
        status_filter=None,
        origin_filter=None,
        group_path=group_path,
        search=None,
        created_from=created_from,
        created_to=created_to,
    )
    if filter_result is None:
        return IngestJobSummaryResponse()
    where_sql, params = filter_result

    rows = repo._execute_all(
        f"""
        SELECT job.status, job.progress_pct, job.stage_progress, COALESCE(job.origin, 'unknown') AS origin, document.clearance_level
        FROM ingest_jobs job
        JOIN documents document ON document.id = job.doc_id
        WHERE {where_sql}
        """,
        tuple(params),
    )
    status_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    origin_counts: dict[str, int] = {}
    total = 0
    for row in rows:
        status_value = str(row["status"])
        origin_value = str(row["origin"] if row["origin"] in JOB_ORIGINS else "unknown")
        stage_progress = row.get("stage_progress")
        stage_value = stage_for_job_status(
            status_value,
            int(row["progress_pct"]),
            stage_progress=stage_progress if isinstance(stage_progress, dict) else None,
        )
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


def _postgres_visible_job_response(
    user: UserRecord,
    repo: DocumentRepository,
    *,
    status_filter: str | None = None,
    origin_filter: IngestJobOrigin | None = None,
    group_path: str | None = None,
    search: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int,
    offset: int,
) -> IngestJobListResponse | None:
    if not isinstance(repo, PostgresDocumentRepository):
        return None
    if not can_read_document_metadata(user):
        return IngestJobListResponse(items=[], total=0, limit=limit, offset=offset)
    filter_result = _postgres_ingest_job_filters(
        user,
        status_filter=status_filter,
        origin_filter=origin_filter,
        group_path=group_path,
        search=search,
        created_from=created_from,
        created_to=created_to,
    )
    if filter_result is None:
        return IngestJobListResponse(items=[], total=0, limit=limit, offset=offset)
    where_sql, params = filter_result
    total_row = repo._execute_one(
        f"""
        SELECT COUNT(*) AS count
        FROM ingest_jobs job
        JOIN documents document ON document.id = job.doc_id
        WHERE {where_sql}
        """,
        tuple(params),
    )
    rows = repo._execute_all(
        f"""
        SELECT
            job.id::text AS id,
            job.doc_id::text AS doc_id,
            COALESCE(job.origin, 'unknown') AS origin,
            job.status,
            job.progress_pct,
            job.stage_progress,
            job.attempt_count,
            job.last_heartbeat_at,
            job.warnings,
            job.parser_provenance,
            job.error_code,
            job.error_message_safe,
            job.created_at,
            job.updated_at,
            job.completed_at,
            COALESCE(document.title, document.id::text) AS document_title,
            document.group_path,
            document.clearance_level
        FROM ingest_jobs job
        JOIN documents document ON document.id = job.doc_id
        WHERE {where_sql}
        ORDER BY job.created_at DESC, job.id DESC
        LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    )
    return IngestJobListResponse(
        items=[_ingest_job_item_from_postgres_row(row) for row in rows],
        total=int(total_row["count"]),
        limit=limit,
        offset=offset,
    )


def _postgres_ingest_job_filters(
    user: UserRecord,
    *,
    status_filter: str | None,
    origin_filter: IngestJobOrigin | None,
    group_path: str | None,
    search: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
) -> tuple[str, list[object]] | None:
    clauses = ["document.clearance_level = ANY(%s::text[])"]
    params: list[object] = [list(clearance_levels_at_or_below(user.clearance_level))]
    if not is_global_admin(user):
        visible_groups = sorted({normalize_group_path(path) for path in user.group_paths})
        if not visible_groups:
            return None
        clauses.append(
            """
            (
                document.group_path = ANY(%s::text[])
                OR EXISTS (
                    SELECT 1
                    FROM document_shares share
                    WHERE share.document_id = document.id
                      AND share.group_path = ANY(%s::text[])
                )
            )
            """
        )
        params.extend([visible_groups, visible_groups])
    if status_filter:
        clauses.append("job.status = %s")
        params.append(status_filter)
    if origin_filter:
        clauses.append("job.origin = %s")
        params.append(origin_filter)
    if group_path:
        clauses.append("document.group_path = %s")
        params.append(group_path)
    query = (search or "").strip().lower()
    if query:
        pattern = f"%{query}%"
        clauses.append(
            """
            (
                lower(job.id::text) LIKE %s
                OR lower(job.doc_id::text) LIKE %s
                OR lower(COALESCE(document.title, '')) LIKE %s
                OR lower(document.group_path) LIKE %s
            )
            """
        )
        params.extend([pattern, pattern, pattern, pattern])
    if created_from:
        clauses.append("job.created_at >= %s")
        params.append(created_from)
    if created_to:
        clauses.append("job.created_at <= %s")
        params.append(created_to)
    return " AND ".join(f"({clause})" for clause in clauses), params


def _ingest_job_item_from_postgres_row(row: dict[str, object]) -> IngestJobItem:
    job = job_from_row(row)
    status_payload = build_job_status_response(job)
    return IngestJobItem(
        **status_payload.model_dump(),
        document_id=job.doc_id,
        document_title=str(row.get("document_title") or job.doc_id),
        group_path=str(row["group_path"]),
        clearance_level=cast(ClearanceLevel, row["clearance_level"]),
        origin=cast(IngestJobOrigin, job.origin if job.origin in JOB_ORIGINS else "unknown"),
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


def _graphrag_worker_snapshot(control: IngestWorkerControl) -> tuple[WorkerControlResult | None, str | None]:
    try:
        return control.snapshot(desired_concurrency=1), None
    except Exception as exc:
        return None, _safe_status_error(exc)


def _redis_queue_length(queue_name: str) -> tuple[int | None, str | None]:
    if settings.ingest_queue_backend == "memory":
        return 0, None
    try:
        from redis import Redis
    except ImportError as exc:
        return None, _safe_status_error(exc)
    try:
        client = Redis.from_url(settings.celery_broker_url or settings.redis_url, decode_responses=False)
        return int(client.llen(queue_name)), None
    except Exception as exc:
        return None, _safe_status_error(exc)


def _redis_queued_graphrag_tasks(queue_name: str, *, limit: int = 25) -> list[GraphRAGQueuedTask]:
    if settings.ingest_queue_backend == "memory":
        return []
    try:
        from redis import Redis
    except ImportError:
        return []
    try:
        client = Redis.from_url(settings.celery_broker_url or settings.redis_url, decode_responses=False)
        raw_items = client.lrange(queue_name, 0, max(0, limit - 1))
    except Exception:
        return []
    tasks: list[GraphRAGQueuedTask] = []
    for raw_item in raw_items:
        task = _graphrag_queued_task_from_redis_item(raw_item)
        if task is not None:
            tasks.append(task)
    return tasks


def _graphrag_queued_task_from_redis_item(raw_item: object) -> GraphRAGQueuedTask | None:
    if isinstance(raw_item, bytes):
        raw_text = raw_item.decode("utf-8", errors="ignore")
    else:
        raw_text = str(raw_item)
    try:
        message = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict):
        return None
    headers = message.get("headers") if isinstance(message.get("headers"), dict) else {}
    task_name = str(headers.get("task") or message.get("task") or "")
    payload = _celery_message_payload(message)
    if not payload:
        return None
    return GraphRAGQueuedTask(
        task_id=str(headers.get("id") or message.get("id") or ""),
        task_name=task_name,
        job_id=str(payload["job_id"]) if payload.get("job_id") else None,
        document_id=str(payload["doc_id"]) if payload.get("doc_id") else None,
    )


def _celery_message_payload(message: dict[str, object]) -> dict[str, object] | None:
    body = message.get("body")
    decoded: object
    if isinstance(body, str):
        try:
            decoded_bytes = base64.b64decode(body)
            decoded = json.loads(decoded_bytes.decode("utf-8"))
        except Exception:
            return None
    else:
        decoded = body
    if isinstance(decoded, list) and decoded:
        args = decoded[0]
        payload = args[0] if isinstance(args, list | tuple) and args else None
        return payload if isinstance(payload, dict) else None
    return decoded if isinstance(decoded, dict) else None


def _graphrag_active_task_response(task: object, now: datetime) -> GraphRAGActiveTask:
    time_start = getattr(task, "time_start", None)
    started_at = datetime.fromtimestamp(time_start, tz=timezone.utc) if isinstance(time_start, int | float) else None
    elapsed_seconds = max(0, int(now.timestamp() - time_start)) if isinstance(time_start, int | float) else None
    return GraphRAGActiveTask(
        task_id=str(getattr(task, "task_id", "")),
        task_name=str(getattr(task, "task_name", "")),
        worker=str(getattr(task, "worker", "")),
        job_id=getattr(task, "job_id", None),
        document_id=getattr(task, "doc_id", None),
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
    )


def _cancel_task_matches(
    task: GraphRAGActiveTask | GraphRAGQueuedTask,
    task_id: str,
    *,
    job_id: str,
    document_id: str,
) -> bool:
    return bool(
        task.task_id == task_id
        and task.task_name == settings.graphrag_index_task_name
        and (
            (task.job_id and task.job_id == job_id)
            or (task.document_id and task.document_id == document_id)
        )
    )


def _safe_status_error(exc: Exception) -> str:
    message = str(exc).strip()
    detail = f": {message[:220]}" if message else ""
    return f"{exc.__class__.__name__}{detail}"


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
