"""Queue dispatch for asynchronous document generation."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from ..core.config import settings


class ArtifactJobQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...


class InMemoryArtifactJobQueue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


class CeleryArtifactJobQueue:
    def __init__(self, *, broker_url: str, queue_name: str, task_name: str, app: Any | None = None) -> None:
        self.queue_name = queue_name
        self.task_name = task_name
        if app is not None:
            self.app = app
            return
        try:
            from celery import Celery
        except ImportError as exc:
            raise RuntimeError("celery package is required for artifact queue dispatch") from exc
        self.app = Celery("agenticrag-artifact-dispatch", broker=broker_url)

    def enqueue(self, job_id: str) -> None:
        try:
            self.app.send_task(self.task_name, args=[job_id], queue=self.queue_name)
        except Exception as exc:
            raise RuntimeError(f"artifact celery enqueue failed: {exc}") from exc


@lru_cache
def default_artifact_job_queue() -> ArtifactJobQueue:
    if settings.artifact_queue_backend == "memory":
        return InMemoryArtifactJobQueue()
    if settings.artifact_queue_backend != "celery":
        raise RuntimeError(f"unsupported artifact queue backend: {settings.artifact_queue_backend}")
    return CeleryArtifactJobQueue(
        broker_url=settings.celery_broker_url or settings.redis_url,
        queue_name=settings.artifact_queue_name,
        task_name=settings.artifact_task_name,
    )


def get_artifact_job_queue() -> ArtifactJobQueue:
    return default_artifact_job_queue()

