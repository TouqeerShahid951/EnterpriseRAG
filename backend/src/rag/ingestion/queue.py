"""Queue dispatch for uploaded documents."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from ..core.config import settings
from .contracts import IngestJobPayload


class IngestQueue(Protocol):
    def enqueue(self, message: IngestJobPayload) -> None: ...
    def cancel(self, job_id: str) -> None: ...


class InMemoryIngestQueue:
    def __init__(self) -> None:
        self.messages: list[IngestJobPayload] = []

    def enqueue(self, message: IngestJobPayload) -> None:
        self.messages.append(message)

    def cancel(self, job_id: str) -> None:
        self.messages = [message for message in self.messages if message.job_id != job_id]


class CeleryIngestQueue:
    def __init__(
        self,
        *,
        broker_url: str,
        queue_name: str,
        task_name: str,
        app: Any | None = None,
    ) -> None:
        self._queue_name = queue_name
        self._task_name = task_name
        if app is not None:
            self._app = app
            return
        try:
            from celery import Celery
        except ImportError as exc:
            raise RuntimeError("celery package is required for ingest queue dispatch") from exc
        self._app = Celery("agenticrag-backend", broker=broker_url)

    def enqueue(self, message: IngestJobPayload) -> None:
        try:
            self._app.send_task(
                self._task_name,
                args=[message.to_dict()],
                queue=self._queue_name,
                task_id=message.job_id,
            )
        except Exception as exc:
            raise RuntimeError(f"celery enqueue failed: {exc}") from exc

    def cancel(self, job_id: str) -> None:
        try:
            self._app.control.revoke(job_id, terminate=False)
        except Exception as exc:
            raise RuntimeError(f"celery cancel failed: {exc}") from exc


@lru_cache
def default_ingest_queue() -> IngestQueue:
    if settings.ingest_queue_backend == "memory":
        return InMemoryIngestQueue()
    if settings.ingest_queue_backend != "celery":
        raise RuntimeError(f"unsupported ingest queue backend: {settings.ingest_queue_backend}")
    return CeleryIngestQueue(
        broker_url=settings.celery_broker_url or settings.redis_url,
        queue_name=settings.ingest_queue_name,
        task_name=settings.ingest_task_name,
    )


def get_ingest_queue() -> IngestQueue:
    return default_ingest_queue()
