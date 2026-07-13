"""Concrete queue adapters for artifact jobs."""

from __future__ import annotations

from typing import Any


class InMemoryArtifactJobQueue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


class CeleryArtifactJobQueue:
    def __init__(
        self,
        *,
        broker_url: str,
        queue_name: str,
        task_name: str,
        app: Any | None = None,
    ) -> None:
        self.queue_name = queue_name
        self.task_name = task_name
        if app is not None:
            self.app = app
            return
        try:
            from celery import Celery
        except ImportError as exc:
            raise RuntimeError(
                "celery package is required for artifact queue dispatch"
            ) from exc
        self.app = Celery("agenticrag-artifact-dispatch", broker=broker_url)

    def enqueue(self, job_id: str) -> None:
        try:
            self.app.send_task(self.task_name, args=[job_id], queue=self.queue_name)
        except Exception as exc:
            raise RuntimeError(f"artifact celery enqueue failed: {exc}") from exc
