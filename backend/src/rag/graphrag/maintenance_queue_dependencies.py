"""Composition provider for the GraphRAG maintenance queue."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .adapters.maintenance_queue import (
    CeleryGraphRAGMaintenanceQueue,
    InMemoryGraphRAGMaintenanceQueue,
)
from .maintenance_queue import GraphRAGMaintenanceQueue


@lru_cache
def default_graphrag_maintenance_queue() -> GraphRAGMaintenanceQueue:
    if settings.ingest_queue_backend == "memory":
        return InMemoryGraphRAGMaintenanceQueue()
    if settings.ingest_queue_backend != "celery":
        raise RuntimeError(
            "unsupported GraphRAG maintenance queue backend: "
            f"{settings.ingest_queue_backend}"
        )
    return CeleryGraphRAGMaintenanceQueue(
        broker_url=settings.celery_broker_url or settings.redis_url,
        queue_name=settings.graphrag_queue_name,
        index_task_name=settings.graphrag_index_task_name,
        rebuild_task_name=settings.graphrag_partition_rebuild_task_name,
    )


def get_graphrag_maintenance_queue() -> GraphRAGMaintenanceQueue:
    return default_graphrag_maintenance_queue()
