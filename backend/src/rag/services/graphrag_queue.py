"""Queue dispatch for GraphRAG maintenance work."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from ..core.config import settings


@dataclass(frozen=True)
class GraphRAGDocumentIndexMessage:
    doc_id: str
    job_id: str
    reason: str


@dataclass(frozen=True)
class GraphRAGPartitionRebuildMessage:
    doc_id: str
    partition_key: str
    reason: str


class GraphRAGMaintenanceQueue(Protocol):
    def cancel(self, task_id: str, *, terminate: bool = False) -> None: ...
    def enqueue_document_index(self, message: GraphRAGDocumentIndexMessage) -> None: ...
    def enqueue_partition_rebuild(self, message: GraphRAGPartitionRebuildMessage) -> None: ...


class InMemoryGraphRAGMaintenanceQueue:
    def __init__(self) -> None:
        self.cancelled_tasks: list[tuple[str, bool]] = []
        self.document_messages: list[GraphRAGDocumentIndexMessage] = []
        self.messages: list[GraphRAGPartitionRebuildMessage] = []

    def cancel(self, task_id: str, *, terminate: bool = False) -> None:
        self.cancelled_tasks.append((task_id, terminate))

    def enqueue_document_index(self, message: GraphRAGDocumentIndexMessage) -> None:
        self.document_messages.append(message)

    def enqueue_partition_rebuild(self, message: GraphRAGPartitionRebuildMessage) -> None:
        self.messages.append(message)


class CeleryGraphRAGMaintenanceQueue:
    def __init__(
        self,
        *,
        broker_url: str,
        queue_name: str,
        index_task_name: str,
        rebuild_task_name: str,
        app: Any | None = None,
    ) -> None:
        self._queue_name = queue_name
        self._index_task_name = index_task_name
        self._rebuild_task_name = rebuild_task_name
        if app is not None:
            self._app = app
            return
        try:
            from celery import Celery
        except ImportError as exc:
            raise RuntimeError("celery package is required for GraphRAG maintenance dispatch") from exc
        self._app = Celery("agenticrag-backend-graphrag", broker=broker_url)

    def cancel(self, task_id: str, *, terminate: bool = False) -> None:
        try:
            options: dict[str, Any] = {"terminate": terminate}
            if terminate:
                options["signal"] = "SIGTERM"
            self._app.control.revoke(task_id, **options)
        except Exception as exc:
            raise RuntimeError(f"graphrag task cancellation failed: {exc}") from exc

    def enqueue_document_index(self, message: GraphRAGDocumentIndexMessage) -> None:
        try:
            self._app.send_task(
                self._index_task_name,
                args=[{
                    "doc_id": message.doc_id,
                    "job_id": message.job_id,
                    "reason": message.reason,
                }],
                queue=self._queue_name,
            )
        except Exception as exc:
            raise RuntimeError(f"graphrag document enqueue failed: {exc}") from exc

    def enqueue_partition_rebuild(self, message: GraphRAGPartitionRebuildMessage) -> None:
        try:
            self._app.send_task(
                self._rebuild_task_name,
                args=[{
                    "doc_id": message.doc_id,
                    "partition_key": message.partition_key,
                    "reason": message.reason,
                }],
                queue=self._queue_name,
            )
        except Exception as exc:
            raise RuntimeError(f"graphrag rebuild enqueue failed: {exc}") from exc


@lru_cache
def default_graphrag_maintenance_queue() -> GraphRAGMaintenanceQueue:
    if settings.ingest_queue_backend == "memory":
        return InMemoryGraphRAGMaintenanceQueue()
    if settings.ingest_queue_backend != "celery":
        raise RuntimeError(f"unsupported GraphRAG maintenance queue backend: {settings.ingest_queue_backend}")
    return CeleryGraphRAGMaintenanceQueue(
        broker_url=settings.celery_broker_url or settings.redis_url,
        queue_name=settings.graphrag_queue_name,
        index_task_name=settings.graphrag_index_task_name,
        rebuild_task_name=settings.graphrag_partition_rebuild_task_name,
    )


def get_graphrag_maintenance_queue() -> GraphRAGMaintenanceQueue:
    return default_graphrag_maintenance_queue()
