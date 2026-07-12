"""Transport-independent GraphRAG worker and queue monitoring."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Protocol

from ..ingestion.worker_control import (
    IngestWorkerControl,
    WorkerCapacity,
    WorkerControlResult,
)


@dataclass(frozen=True)
class GraphRAGQueuedTaskRecord:
    task_id: str
    task_name: str
    job_id: str | None = None
    document_id: str | None = None


@dataclass(frozen=True)
class GraphRAGActiveTaskRecord:
    task_id: str
    task_name: str
    worker: str
    job_id: str | None = None
    document_id: str | None = None
    started_at: datetime | None = None
    elapsed_seconds: int | None = None


@dataclass(frozen=True)
class GraphRAGMonitoringStatus:
    enabled: bool
    queue_name: str
    queued_jobs: int | None
    queue_error: str | None
    worker_online: bool
    worker_error: str | None
    active_jobs: int
    observed_pool_size: int
    workers: tuple[WorkerCapacity, ...]
    active_tasks: tuple[GraphRAGActiveTaskRecord, ...]
    queued_tasks: tuple[GraphRAGQueuedTaskRecord, ...]


class GraphRAGQueueMonitor(Protocol):
    def queue_length(self, queue_name: str) -> int: ...

    def queued_tasks(
        self,
        queue_name: str,
        *,
        limit: int = 25,
    ) -> tuple[GraphRAGQueuedTaskRecord, ...]: ...


def inspect_graphrag_status(
    *,
    enabled: bool,
    queue_name: str,
    control: IngestWorkerControl,
    queue_monitor: GraphRAGQueueMonitor,
    now: datetime | None = None,
) -> GraphRAGMonitoringStatus:
    """Collect a degraded-but-useful GraphRAG operational snapshot."""

    worker_snapshot, worker_error = snapshot_graphrag_worker(control)
    queued_jobs, queue_error = observe_queue_length(queue_monitor, queue_name)
    queued_tasks = observe_queued_tasks(queue_monitor, queue_name)
    observed_at = now or datetime.now(UTC)
    return GraphRAGMonitoringStatus(
        enabled=enabled,
        queue_name=queue_name,
        queued_jobs=queued_jobs,
        queue_error=queue_error,
        worker_online=bool(worker_snapshot and worker_snapshot.worker_online),
        worker_error=worker_error,
        active_jobs=worker_snapshot.active_jobs if worker_snapshot else 0,
        observed_pool_size=(
            worker_snapshot.observed_pool_size if worker_snapshot else 0
        ),
        workers=worker_snapshot.workers if worker_snapshot else (),
        active_tasks=tuple(
            active_task_record(task, observed_at)
            for task in (worker_snapshot.active_tasks if worker_snapshot else ())
        ),
        queued_tasks=queued_tasks,
    )


def snapshot_graphrag_worker(
    control: IngestWorkerControl,
) -> tuple[WorkerControlResult | None, str | None]:
    try:
        return control.snapshot(desired_concurrency=1), None
    except Exception as exc:
        return None, safe_status_error(exc)


def observe_queue_length(
    monitor: GraphRAGQueueMonitor,
    queue_name: str,
) -> tuple[int | None, str | None]:
    try:
        return int(monitor.queue_length(queue_name)), None
    except Exception as exc:
        return None, safe_status_error(exc)


def observe_queued_tasks(
    monitor: GraphRAGQueueMonitor,
    queue_name: str,
    *,
    limit: int = 25,
) -> tuple[GraphRAGQueuedTaskRecord, ...]:
    try:
        return monitor.queued_tasks(queue_name, limit=limit)
    except Exception:
        return ()


def parse_queued_graphrag_task(
    raw_item: object,
) -> GraphRAGQueuedTaskRecord | None:
    """Decode the Celery Redis message format used by GraphRAG tasks."""

    raw_text = (
        raw_item.decode("utf-8", errors="ignore")
        if isinstance(raw_item, bytes)
        else str(raw_item)
    )
    try:
        message = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict):
        return None
    headers = message.get("headers") if isinstance(message.get("headers"), dict) else {}
    payload = _celery_message_payload(message)
    if not payload:
        return None
    return GraphRAGQueuedTaskRecord(
        task_id=str(headers.get("id") or message.get("id") or ""),
        task_name=str(headers.get("task") or message.get("task") or ""),
        job_id=str(payload["job_id"]) if payload.get("job_id") else None,
        document_id=str(payload["doc_id"]) if payload.get("doc_id") else None,
    )


def active_task_record(task: object, now: datetime) -> GraphRAGActiveTaskRecord:
    time_start = getattr(task, "time_start", None)
    started_at = (
        datetime.fromtimestamp(time_start, tz=UTC)
        if isinstance(time_start, int | float)
        else None
    )
    elapsed_seconds = (
        max(0, int(now.timestamp() - time_start))
        if isinstance(time_start, int | float)
        else None
    )
    return GraphRAGActiveTaskRecord(
        task_id=str(getattr(task, "task_id", "")),
        task_name=str(getattr(task, "task_name", "")),
        worker=str(getattr(task, "worker", "")),
        job_id=getattr(task, "job_id", None),
        document_id=getattr(task, "doc_id", None),
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
    )


def safe_status_error(exc: Exception) -> str:
    message = str(exc).strip()
    detail = f": {message[:220]}" if message else ""
    return f"{exc.__class__.__name__}{detail}"


def _celery_message_payload(
    message: dict[str, object],
) -> dict[str, object] | None:
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
