"""Queue dispatch for asynchronous RAG evaluation runs."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from ..core.config import settings


class EvaluationRunQueue(Protocol):
    def enqueue(self, run_id: str) -> None: ...


class InMemoryEvaluationRunQueue:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def enqueue(self, run_id: str) -> None:
        self.run_ids.append(run_id)


class CeleryEvaluationRunQueue:
    def __init__(self, *, broker_url: str, queue_name: str, task_name: str, app: Any | None = None) -> None:
        self.queue_name = queue_name
        self.task_name = task_name
        if app is not None:
            self.app = app
            return
        try:
            from celery import Celery
        except ImportError as exc:
            raise RuntimeError("celery package is required for evaluation queue dispatch") from exc
        self.app = Celery("agenticrag-evaluation-dispatch", broker=broker_url)

    def enqueue(self, run_id: str) -> None:
        try:
            self.app.send_task(self.task_name, args=[run_id], queue=self.queue_name)
        except Exception as exc:
            raise RuntimeError(f"evaluation celery enqueue failed: {exc}") from exc


@lru_cache
def default_evaluation_run_queue() -> EvaluationRunQueue:
    if settings.evaluation_queue_backend == "memory":
        return InMemoryEvaluationRunQueue()
    if settings.evaluation_queue_backend != "celery":
        raise RuntimeError(f"unsupported evaluation queue backend: {settings.evaluation_queue_backend}")
    return CeleryEvaluationRunQueue(
        broker_url=settings.celery_broker_url or settings.redis_url,
        queue_name=settings.evaluation_queue_name,
        task_name=settings.evaluation_task_name,
    )


def get_evaluation_run_queue() -> EvaluationRunQueue:
    return default_evaluation_run_queue()
