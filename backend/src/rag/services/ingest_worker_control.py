"""Celery remote control for ingestion worker capacity."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from time import monotonic
from typing import Any

from ..core.config import settings

SNAPSHOT_CACHE_SECONDS = 3.0
INSPECT_TIMEOUT_SECONDS = 0.5


@dataclass(frozen=True)
class WorkerCapacity:
    name: str
    pool_size: int
    active_jobs: int


@dataclass(frozen=True)
class WorkerActiveTask:
    task_id: str
    task_name: str
    worker: str
    job_id: str | None = None
    doc_id: str | None = None
    time_start: float | None = None


@dataclass(frozen=True)
class WorkerControlResult:
    desired_concurrency: int
    workers: tuple[WorkerCapacity, ...]
    apply_status: str
    active_job_ids: frozenset[str] = frozenset()
    active_tasks: tuple[WorkerActiveTask, ...] = ()

    @property
    def worker_online(self) -> bool:
        return bool(self.workers)

    @property
    def observed_pool_size(self) -> int:
        return sum(worker.pool_size for worker in self.workers)

    @property
    def active_jobs(self) -> int:
        return sum(worker.active_jobs for worker in self.workers)


class IngestWorkerControl:
    def __init__(self, *, broker_url: str, queue_name: str = "ingest:jobs", app: Any | None = None) -> None:
        if app is None:
            from celery import Celery

            app = Celery("agenticrag-ingest-control", broker=broker_url)
        self._app = app
        self._queue_name = queue_name
        self._snapshot_cache: dict[int, tuple[float, WorkerControlResult]] = {}

    def snapshot(self, desired_concurrency: int) -> WorkerControlResult:
        now = monotonic()
        cached = self._snapshot_cache.get(desired_concurrency)
        if cached and now - cached[0] < SNAPSHOT_CACHE_SECONDS:
            return cached[1]

        inspector = self._app.control.inspect(timeout=INSPECT_TIMEOUT_SECONDS)
        stats = inspector.stats() or {}
        active = inspector.active() or {}
        active_queues = inspector.active_queues() or {}
        workers: list[WorkerCapacity] = []
        active_job_ids: set[str] = set()
        active_tasks: list[WorkerActiveTask] = []
        for name, worker_stats in stats.items():
            if not _is_ingest_worker(name, active_queues.get(name), self._queue_name):
                continue
            tasks = active.get(name, [])
            worker_tasks = _active_tasks(name, tasks)
            workers.append(
                WorkerCapacity(
                    name=name,
                    pool_size=_pool_size(worker_stats),
                    active_jobs=len(tasks),
                )
            )
            active_tasks.extend(worker_tasks)
            active_job_ids.update(task.job_id for task in worker_tasks if task.job_id)
        status = "pending" if not workers else (
            "applied" if all(worker.pool_size == desired_concurrency for worker in workers) else "draining"
        )
        result = WorkerControlResult(
            desired_concurrency,
            tuple(workers),
            status,
            frozenset(active_job_ids),
            tuple(active_tasks),
        )
        self._snapshot_cache[desired_concurrency] = (now, result)
        return result

    def apply(self, desired_concurrency: int) -> WorkerControlResult:
        self._snapshot_cache.clear()
        current = self.snapshot(desired_concurrency)
        if not current.worker_online:
            return current
        for worker in current.workers:
            difference = desired_concurrency - worker.pool_size
            if difference > 0:
                self._app.control.pool_grow(difference, reply=True, destination=[worker.name])
            elif difference < 0:
                self._app.control.pool_shrink(abs(difference), reply=True, destination=[worker.name])
        self._snapshot_cache.clear()
        return self.snapshot(desired_concurrency)


def _pool_size(stats: dict[str, Any]) -> int:
    pool = stats.get("pool")
    if isinstance(pool, dict):
        for key in ("max-concurrency", "max_concurrency"):
            value = pool.get(key)
            if isinstance(value, int):
                return value
        value = pool.get("processes")
        if isinstance(value, list):
            return len(value)
    return 0


def _is_ingest_worker(name: str, queues: Any, queue_name: str) -> bool:
    if isinstance(queues, list):
        return any(_queue_name(queue) == queue_name for queue in queues)
    # Hostname fallback for older Celery responses that do not include active_queues.
    if queue_name == "ingest:jobs":
        return "ingestion-worker" in name
    if queue_name == "graphrag:jobs":
        return "graphrag-worker" in name
    return queue_name.replace(":jobs", "-worker").replace(":", "-") in name


def _active_tasks(worker_name: str, tasks: list[dict[str, Any]]) -> tuple[WorkerActiveTask, ...]:
    active_tasks: list[WorkerActiveTask] = []
    for task in tasks:
        payload = _task_payload(task)
        job_id = payload.get("job_id") if payload else None
        doc_id = payload.get("doc_id") if payload else None
        time_start = task.get("time_start")
        active_tasks.append(
            WorkerActiveTask(
                task_id=str(task.get("id") or task.get("task_id") or ""),
                task_name=str(task.get("name") or ""),
                worker=worker_name,
                job_id=str(job_id) if job_id else None,
                doc_id=str(doc_id) if doc_id else None,
                time_start=float(time_start) if isinstance(time_start, int | float) else None,
            )
        )
    return tuple(active_tasks)


def _task_payload(task: dict[str, Any]) -> dict[str, Any] | None:
    args = task.get("args")
    payload = args[0] if isinstance(args, list | tuple) and args else None
    return payload if isinstance(payload, dict) else None


def _queue_name(queue: Any) -> str | None:
    if isinstance(queue, dict):
        value = queue.get("name")
        return str(value) if value else None
    value = getattr(queue, "name", None)
    return str(value) if value else None


@lru_cache
def default_ingest_worker_control() -> IngestWorkerControl:
    return IngestWorkerControl(
        broker_url=settings.celery_broker_url or settings.redis_url,
        queue_name=settings.ingest_queue_name,
    )


def get_ingest_worker_control() -> IngestWorkerControl:
    return default_ingest_worker_control()


@lru_cache
def default_graphrag_worker_control() -> IngestWorkerControl:
    return IngestWorkerControl(
        broker_url=settings.celery_broker_url or settings.redis_url,
        queue_name=settings.graphrag_queue_name,
    )


def get_graphrag_worker_control() -> IngestWorkerControl:
    return default_graphrag_worker_control()
