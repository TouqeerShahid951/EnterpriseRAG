"""Celery remote control for ingestion worker capacity."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..core.config import settings


@dataclass(frozen=True)
class WorkerCapacity:
    name: str
    pool_size: int
    active_jobs: int


@dataclass(frozen=True)
class WorkerControlResult:
    desired_concurrency: int
    workers: tuple[WorkerCapacity, ...]
    apply_status: str
    active_job_ids: frozenset[str] = frozenset()

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
    def __init__(self, *, broker_url: str, app: Any | None = None) -> None:
        if app is None:
            from celery import Celery

            app = Celery("agenticrag-ingest-control", broker=broker_url)
        self._app = app

    def snapshot(self, desired_concurrency: int) -> WorkerControlResult:
        inspector = self._app.control.inspect(timeout=2)
        stats = inspector.stats() or {}
        active = inspector.active() or {}
        workers: list[WorkerCapacity] = []
        active_job_ids: set[str] = set()
        for name, worker_stats in stats.items():
            if not _is_ingest_worker(name, worker_stats):
                continue
            tasks = active.get(name, [])
            workers.append(
                WorkerCapacity(
                    name=name,
                    pool_size=_pool_size(worker_stats),
                    active_jobs=len(tasks),
                )
            )
            active_job_ids.update(_job_ids(tasks))
        status = "pending" if not workers else (
            "applied" if all(worker.pool_size == desired_concurrency for worker in workers) else "draining"
        )
        return WorkerControlResult(desired_concurrency, tuple(workers), status, frozenset(active_job_ids))

    def apply(self, desired_concurrency: int) -> WorkerControlResult:
        current = self.snapshot(desired_concurrency)
        if not current.worker_online:
            return current
        for worker in current.workers:
            difference = desired_concurrency - worker.pool_size
            if difference > 0:
                self._app.control.pool_grow(difference, reply=True, destination=[worker.name])
            elif difference < 0:
                self._app.control.pool_shrink(abs(difference), reply=True, destination=[worker.name])
        return self.snapshot(desired_concurrency)


def _pool_size(stats: dict[str, Any]) -> int:
    pool = stats.get("pool")
    if isinstance(pool, dict):
        for key in ("processes", "max-concurrency", "max_concurrency"):
            value = pool.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, int):
                return value
    return 0


def _is_ingest_worker(name: str, stats: dict[str, Any]) -> bool:
    queues = stats.get("total")
    return "ingestion-worker" in name or "rag" in name or queues is not None


def _job_ids(tasks: list[dict[str, Any]]) -> set[str]:
    job_ids: set[str] = set()
    for task in tasks:
        args = task.get("args")
        payload = args[0] if isinstance(args, list) and args else None
        if isinstance(payload, dict) and payload.get("job_id"):
            job_ids.add(str(payload["job_id"]))
    return job_ids


@lru_cache
def default_ingest_worker_control() -> IngestWorkerControl:
    return IngestWorkerControl(broker_url=settings.celery_broker_url or settings.redis_url)


def get_ingest_worker_control() -> IngestWorkerControl:
    return default_ingest_worker_control()
