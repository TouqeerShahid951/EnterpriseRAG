"""Ingestion-job-scoped GraphRAG routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.dependencies import require_csrf, require_current_user
from ..auth.document_access import can_manage_document_ingestion
from ..auth.identity_models import UserRecord
from ..auth.permissions import can_read_document_metadata
from ..core.config import settings
from ..documents.repository import DocumentRepository, get_document_repository
from ..ingestion.configuration import IngestConfigRepository
from ..ingestion.configuration_dependencies import (
    effective_ingest_config,
    get_ingest_config_repository,
)
from ..ingestion.job_dependencies import get_ingest_job_repository
from ..ingestion.job_models import IngestJobRepository
from ..ingestion.worker_control import (
    IngestWorkerControl,
    WorkerControlResult,
    get_graphrag_worker_control,
)
from ..schemas.common import ErrorResponse
from ..schemas.ingest_jobs import (
    GraphRAGActiveTask,
    GraphRAGCancelRequest,
    GraphRAGCancelResponse,
    GraphRAGQueuedTask,
    GraphRAGStatusResponse,
    GraphRAGWorkerState,
)
from .maintenance_queue import GraphRAGMaintenanceQueue
from .maintenance_queue_dependencies import get_graphrag_maintenance_queue
from .monitoring import (
    GraphRAGQueueMonitor,
    active_task_record,
    inspect_graphrag_status,
    observe_queue_length,
    observe_queued_tasks,
    parse_queued_graphrag_task,
    snapshot_graphrag_worker,
)
from .monitoring_dependencies import get_graphrag_queue_monitor

router = APIRouter(prefix="/ingest-jobs", tags=["ingest-jobs"])


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
            detail={
                "code": "graphrag_status_forbidden",
                "message": "User cannot view ingestion health.",
            },
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
            GraphRAGWorkerState(
                name=worker.name,
                pool_size=worker.pool_size,
                active_jobs=worker.active_jobs,
            )
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
            detail={
                "code": "job_not_found",
                "message": "Ingestion job was not found.",
            },
        )
    document = repo.get_document(job.doc_id, include_deleted=True)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "document_not_found",
                "message": "Ingested document was not found.",
            },
        )
    if not can_manage_document_ingestion(user, document):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "graphrag_cancel_forbidden",
                "message": (
                    "Only the uploader or a scoped admin can cancel graph "
                    "enrichment for this document."
                ),
            },
        )
    snapshot, worker_error = _graphrag_worker_snapshot(control)
    active_tasks = [
        _graphrag_active_task_response(task, datetime.now(timezone.utc))
        for task in (snapshot.active_tasks if snapshot else ())
    ]
    queued_tasks = _redis_queued_graphrag_tasks(settings.graphrag_queue_name)
    active_task = next(
        (
            task
            for task in active_tasks
            if _cancel_task_matches(
                task,
                payload.task_id,
                job_id=job.id,
                document_id=document.id,
            )
        ),
        None,
    )
    queued_task = next(
        (
            task
            for task in queued_tasks
            if _cancel_task_matches(
                task,
                payload.task_id,
                job_id=job.id,
                document_id=document.id,
            )
        ),
        None,
    )
    if active_task is None and queued_task is None:
        _, queue_error = _redis_queue_length(settings.graphrag_queue_name)
        if worker_error and queue_error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "graphrag_status_unavailable",
                    "message": "Graph task activity could not be verified.",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "graphrag_task_not_active",
                "message": "Graph enrichment is no longer queued or running.",
            },
        )
    terminate = active_task is not None
    try:
        queue.cancel(payload.task_id, terminate=terminate)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "graphrag_cancel_failed",
                "message": "Graph enrichment could not be cancelled.",
            },
        ) from exc
    repo.append_audit_event(
        event_type="documents.graph_enrichment.cancelled",
        actor_id=user.id,
        target_type="document",
        target_id=document.id,
        payload={
            "job_id": job.id,
            "task_id": payload.task_id,
            "was_running": terminate,
        },
    )
    return GraphRAGCancelResponse(
        task_id=payload.task_id,
        job_id=job.id,
        document_id=document.id,
        message=(
            "Running graph enrichment cancelled."
            if terminate
            else "Queued graph enrichment cancelled."
        ),
    )


def _graphrag_worker_snapshot(
    control: IngestWorkerControl,
) -> tuple[WorkerControlResult | None, str | None]:
    return snapshot_graphrag_worker(control)


def _redis_queue_length(queue_name: str) -> tuple[int | None, str | None]:
    return observe_queue_length(get_graphrag_queue_monitor(), queue_name)


def _redis_queued_graphrag_tasks(
    queue_name: str,
    *,
    limit: int = 25,
) -> list[GraphRAGQueuedTask]:
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


def _graphrag_queued_task_from_redis_item(
    raw_item: object,
) -> GraphRAGQueuedTask | None:
    task = parse_queued_graphrag_task(raw_item)
    if task is None:
        return None
    return GraphRAGQueuedTask(
        task_id=task.task_id,
        task_name=task.task_name,
        job_id=task.job_id,
        document_id=task.document_id,
    )


def _graphrag_active_task_response(
    task: object,
    now: datetime,
) -> GraphRAGActiveTask:
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
