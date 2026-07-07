"""Queue dispatch for uploaded documents."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from ..core.config import settings
from ..shared.contracts.clearance import DEFAULT_CLEARANCE_LEVEL, normalize_clearance_level
from ..shared.ingestion_quality import normalize_ingestion_quality_preset


@dataclass(frozen=True)
class IngestQueueMessage:
    job_id: str
    doc_id: str
    file_path: str
    group_path: str
    effective_date: str | None
    supersedes: list[str]
    acl_group_paths: list[str] | None = None
    doc_type: str | None = None
    clearance_level: str = DEFAULT_CLEARANCE_LEVEL
    expiry_date: str | None = None
    description: str | None = None
    content_type: str | None = None
    quality_preset: str | None = None
    review_batch_id: str | None = None
    image_review_batch_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "IngestQueueMessage":
        raw_supersedes = payload.get("supersedes", [])
        supersedes = [str(item) for item in raw_supersedes] if isinstance(raw_supersedes, list) else []
        raw_acl_group_paths = payload.get("acl_group_paths")
        acl_group_paths = [str(item) for item in raw_acl_group_paths] if isinstance(raw_acl_group_paths, list) else None
        return cls(
            job_id=str(payload["job_id"]),
            doc_id=str(payload["doc_id"]),
            file_path=str(payload["file_path"]),
            group_path=str(payload["group_path"]),
            clearance_level=normalize_clearance_level(payload.get("clearance_level")),
            effective_date=str(payload["effective_date"]) if payload.get("effective_date") else None,
            supersedes=supersedes,
            acl_group_paths=acl_group_paths,
            doc_type=str(payload["doc_type"]) if payload.get("doc_type") else None,
            expiry_date=str(payload["expiry_date"]) if payload.get("expiry_date") else None,
            description=str(payload["description"]) if payload.get("description") else None,
            content_type=str(payload["content_type"]) if payload.get("content_type") else None,
            quality_preset=normalize_ingestion_quality_preset(payload.get("quality_preset")) if payload.get("quality_preset") else None,
            review_batch_id=str(payload["review_batch_id"]) if payload.get("review_batch_id") else None,
            image_review_batch_id=str(payload["image_review_batch_id"]) if payload.get("image_review_batch_id") else None,
        )


class IngestQueue(Protocol):
    def enqueue(self, message: IngestQueueMessage) -> None: ...
    def cancel(self, job_id: str) -> None: ...


class InMemoryIngestQueue:
    def __init__(self) -> None:
        self.messages: list[IngestQueueMessage] = []

    def enqueue(self, message: IngestQueueMessage) -> None:
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

    def enqueue(self, message: IngestQueueMessage) -> None:
        try:
            self._app.send_task(
                self._task_name,
                args=[_message_payload(message)],
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


def _message_payload(message: IngestQueueMessage) -> dict[str, Any]:
    payload = {
        "job_id": message.job_id,
        "doc_id": message.doc_id,
        "file_path": message.file_path,
        "group_path": message.group_path,
        "clearance_level": message.clearance_level,
        "supersedes": message.supersedes,
    }
    if message.acl_group_paths is not None:
        payload["acl_group_paths"] = list(message.acl_group_paths)
    if message.doc_type:
        payload["doc_type"] = message.doc_type
    if message.effective_date:
        payload["effective_date"] = message.effective_date
    if message.expiry_date:
        payload["expiry_date"] = message.expiry_date
    if message.description:
        payload["description"] = message.description
    if message.content_type:
        payload["content_type"] = message.content_type
    if message.quality_preset:
        payload["quality_preset"] = message.quality_preset
    if message.review_batch_id:
        payload["review_batch_id"] = message.review_batch_id
    if message.image_review_batch_id:
        payload["image_review_batch_id"] = message.image_review_batch_id
    return payload
