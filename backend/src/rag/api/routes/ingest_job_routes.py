"""Scoped ingestion job history and health summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_admin_user, require_csrf, require_current_user
from ...auth.document_access import can_manage_document_ingestion
from ...auth.permissions import can_read_document_metadata, is_global_admin
from ...core.config import settings
from ...shared.contracts.clearance import ClearanceLevel, clearance_levels_at_or_below
from ...documents.repository import DocumentRepository, get_document_repository
from ...graphrag.monitoring import (
    GraphRAGQueueMonitor,
    active_task_record,
    inspect_graphrag_status,
    observe_queue_length,
    observe_queued_tasks,
    parse_queued_graphrag_task,
    snapshot_graphrag_worker,
)
from ...graphrag.monitoring_dependencies import get_graphrag_queue_monitor
from ...ingestion.job_models import (
    IngestJobAccess,
    IngestJobFilters,
    IngestJobRepository,
    IngestJobSearchRepository,
    IngestJobView,
)
from ...ingestion.job_dependencies import get_ingest_job_repository
from ...auth.identity_models import UserRecord
from ...ingestion.configuration import IngestConfigRepository
from ...ingestion.configuration_dependencies import effective_ingest_config, get_ingest_config_repository
from ...ingestion.cancellation import (
    CancelIngestJob,
    DocumentVectorCleaner,
    IngestCancellationError,
)
from ...ingestion.cancellation_dependencies import get_document_vector_cleaner
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
from ...ingestion.queue import IngestQueue, get_ingest_queue
from ...services.graphrag_queue import GraphRAGMaintenanceQueue, get_graphrag_maintenance_queue
from ...ingestion.recovery import (
    IngestRecoveryError,
    MAX_INGEST_ATTEMPTS,
)
from ...ingestion.monitoring import (
    IngestWorkerStatusUnavailable,
    inspect_stale_ingest_jobs,
    requeue_stale_job as requeue_stale_ingest_job,
    search_visible_ingest_jobs,
    summarize_visible_ingest_jobs,
)
from ...ingestion.worker_control import (
    IngestWorkerControl,
    WorkerControlResult,
    get_graphrag_worker_control,
    get_ingest_worker_control,
)
from ...documents.upload_status import build_job_status_response


router = APIRouter(prefix="/ingest-jobs", tags=["ingest-jobs"])

JOB_STATUSES = {"scheduled", "queued", "processing", "complete", "failed", "human_review", "cancelled"}
JOB_ORIGINS = {"upload", "reingest", "restore", "folder", "connector", "unknown"}

_INGEST_CANCELLATION_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
}


@router.get("", response_model=IngestJobListResponse, summary="List visible ingestion jobs")
async def list_ingest_jobs(
    job_status: str | None = Query(default=None, alias="status"),
    origin: str | None = Query(default=None),
    group_path: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    uploaded_by_me: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: UserRecord = Depends(require_current_user),
    job_repo: IngestJobSearchRepository = Depends(get_ingest_job_repository),
) -> IngestJobListResponse:
    status_filter = _job_status(job_status)
    origin_filter = _job_origin(origin)
    normalized_group = normalize_group_path(group_path) if group_path else None
    page = search_visible_ingest_jobs(
        repo=job_repo,
        access=_ingest_job_access(user),
        filters=IngestJobFilters(
            status=status_filter,
            origin=origin_filter,
            group_path=normalized_group,
            search=search,
            created_from=created_from,
            created_to=created_to,
            uploaded_by_user_id=user.id if uploaded_by_me else None,
        ),
        can_view=can_read_document_metadata(user),
        limit=limit,
        offset=offset,
    )
    return IngestJobListResponse(
        items=[_ingest_job_item_from_view(view) for view in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=IngestJobSummaryResponse, summary="Summarize visible ingestion jobs")
async def summarize_ingest_jobs(
    group_path: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    user: UserRecord = Depends(require_current_user),
    job_repo: IngestJobSearchRepository = Depends(get_ingest_job_repository),
) -> IngestJobSummaryResponse:
    normalized_group = normalize_group_path(group_path) if group_path else None
    summary = summarize_visible_ingest_jobs(
        repo=job_repo,
        access=_ingest_job_access(user),
        filters=IngestJobFilters(
            group_path=normalized_group,
            created_from=created_from,
            created_to=created_to,
        ),
        can_view=can_read_document_metadata(user),
    )
    return IngestJobSummaryResponse(
        total=summary.total,
        active=summary.active,
        needs_attention=summary.needs_attention,
        status_counts=summary.status_counts,
        stage_counts=summary.stage_counts,
        origin_counts=summary.origin_counts,
    )


@router.get(
    "/graphrag-status",
    response_model=GraphRAGStatusResponse,
    summary="Show GraphRAG queue and worker activity",
)
async def get_graphrag_status(
    user: UserRecord = Depends(require_current_user),
    control: IngestWorkerControl = Depends(get_graphrag_worker_control),
    config_repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    queue_monitor: GraphRAGQueueMonitor = Depends(get_graphrag_queue_monitor),
) -> GraphRAGStatusResponse:
    if not can_read_document_metadata(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "graphrag_status_forbidden", "message": "User cannot view ingestion health."},
        )
    config = effective_ingest_config(repo=config_repo)
    snapshot = inspect_graphrag_status(
        enabled=settings.graphrag_enabled and config.graph_enrichment_enabled,
        queue_name=settings.graphrag_queue_name,
        control=control,
        queue_monitor=queue_monitor,
    )
    return GraphRAGStatusResponse(
        enabled=snapshot.enabled,
        queue_name=snapshot.queue_name,
        queued_jobs=snapshot.queued_jobs,
        queue_error=snapshot.queue_error,
        worker_online=snapshot.worker_online,
        worker_error=snapshot.worker_error,
        active_jobs=snapshot.active_jobs,
        observed_pool_size=snapshot.observed_pool_size,
        workers=[
            GraphRAGWorkerState(name=worker.name, pool_size=worker.pool_size, active_jobs=worker.active_jobs)
            for worker in snapshot.workers
        ],
        active_tasks=[
            GraphRAGActiveTask(
                task_id=task.task_id,
                task_name=task.task_name,
                worker=task.worker,
                job_id=task.job_id,
                document_id=task.document_id,
                started_at=task.started_at,
                elapsed_seconds=task.elapsed_seconds,
            )
            for task in snapshot.active_tasks
        ],
        queued_tasks=[
            GraphRAGQueuedTask(
                task_id=task.task_id,
                task_name=task.task_name,
                job_id=task.job_id,
                document_id=task.document_id,
            )
            for task in snapshot.queued_tasks
        ],
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
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    control: IngestWorkerControl = Depends(get_graphrag_worker_control),
    queue: GraphRAGMaintenanceQueue = Depends(get_graphrag_maintenance_queue),
) -> GraphRAGCancelResponse:
    require_csrf(request)
    job = job_repo.get_ingest_job(job_id)
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
    if not can_manage_document_ingestion(user, document):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "graphrag_cancel_forbidden", "message": "Only the uploader or a scoped admin can cancel graph enrichment for this document."},
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
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    queue: IngestQueue = Depends(get_ingest_queue),
    vector_cleaner: DocumentVectorCleaner = Depends(get_document_vector_cleaner),
) -> IngestJobCancelResponse:
    require_csrf(request)
    try:
        result = CancelIngestJob(
            document_repo=repo,
            job_repo=job_repo,
            queue=queue,
            vector_cleaner=vector_cleaner,
        ).execute(job_id=job_id, actor=user)
    except IngestCancellationError as exc:
        raise HTTPException(
            status_code=_INGEST_CANCELLATION_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return IngestJobCancelResponse(
        job_id=result.job_id,
        status=result.status,  # type: ignore[arg-type]
        message=result.message,
    )


@router.get(
    "/stale",
    response_model=StaleIngestJobListResponse,
    summary="List stale ingestion jobs eligible for admin recovery",
)
async def list_stale_jobs(
    user: UserRecord = Depends(require_admin_user),
    repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    config_repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    control: IngestWorkerControl = Depends(get_ingest_worker_control),
) -> StaleIngestJobListResponse:
    _ = user
    config = effective_ingest_config(repo=config_repo)
    try:
        overview = inspect_stale_ingest_jobs(
            document_repo=repo,
            job_repo=job_repo,
            control=control,
            desired_concurrency=config.worker_concurrency,
            stale_after_seconds=settings.ingest_stale_after_seconds,
        )
    except IngestWorkerStatusUnavailable as exc:
        raise _worker_status_unavailable() from exc
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
        for candidate in overview.candidates
    ]
    return StaleIngestJobListResponse(
        items=items,
        total=len(items),
        recoverable=overview.recoverable,
        stale_after_seconds=overview.stale_after_seconds,
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
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    queue: IngestQueue = Depends(get_ingest_queue),
    config_repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    control: IngestWorkerControl = Depends(get_ingest_worker_control),
) -> IngestJobRecoveryResponse:
    config = effective_ingest_config(repo=config_repo)
    try:
        job = requeue_stale_ingest_job(
            document_repo=repo,
            job_repo=job_repo,
            queue=queue,
            control=control,
            desired_concurrency=config.worker_concurrency,
            job_id=job_id,
            stale_after_seconds=settings.ingest_stale_after_seconds,
            actor_id=user.id,
            audit_event_type="admin.ingest.requeued",
        )
    except IngestWorkerStatusUnavailable as exc:
        raise _worker_status_unavailable() from exc
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


def _ingest_job_access(user: UserRecord) -> IngestJobAccess:
    return IngestJobAccess(
        clearance_levels=tuple(clearance_levels_at_or_below(user.clearance_level)),
        group_paths=(
            None
            if is_global_admin(user)
            else tuple(sorted({normalize_group_path(path) for path in user.group_paths}))
        ),
    )


def _ingest_job_item_from_view(view: IngestJobView) -> IngestJobItem:
    job = view.job
    status_payload = build_job_status_response(job)
    return IngestJobItem(
        **status_payload.model_dump(),
        document_id=job.doc_id,
        document_title=view.document_title or job.doc_id,
        retry_of_job_id=job.retry_of_job_id,
        group_path=view.group_path,
        clearance_level=cast(ClearanceLevel, view.clearance_level),
        uploaded_by=view.uploaded_by,
        origin=cast(IngestJobOrigin, job.origin if job.origin in JOB_ORIGINS else "unknown"),
    )


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


def _graphrag_worker_snapshot(control: IngestWorkerControl) -> tuple[WorkerControlResult | None, str | None]:
    return snapshot_graphrag_worker(control)


def _redis_queue_length(queue_name: str) -> tuple[int | None, str | None]:
    return observe_queue_length(get_graphrag_queue_monitor(), queue_name)


def _redis_queued_graphrag_tasks(queue_name: str, *, limit: int = 25) -> list[GraphRAGQueuedTask]:
    return [
        GraphRAGQueuedTask(
            task_id=task.task_id,
            task_name=task.task_name,
            job_id=task.job_id,
            document_id=task.document_id,
        )
        for task in observe_queued_tasks(
            get_graphrag_queue_monitor(),
            queue_name,
            limit=limit,
        )
    ]


def _graphrag_queued_task_from_redis_item(raw_item: object) -> GraphRAGQueuedTask | None:
    task = parse_queued_graphrag_task(raw_item)
    if task is None:
        return None
    return GraphRAGQueuedTask(
        task_id=task.task_id,
        task_name=task.task_name,
        job_id=task.job_id,
        document_id=task.document_id,
    )


def _graphrag_active_task_response(task: object, now: datetime) -> GraphRAGActiveTask:
    record = active_task_record(task, now)
    return GraphRAGActiveTask(
        task_id=record.task_id,
        task_name=record.task_name,
        worker=record.worker,
        job_id=record.job_id,
        document_id=record.document_id,
        started_at=record.started_at,
        elapsed_seconds=record.elapsed_seconds,
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


def _worker_status_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "ingest_worker_status_unavailable",
            "message": "Worker activity could not be verified, so stale-job recovery is temporarily disabled.",
        },
    )
