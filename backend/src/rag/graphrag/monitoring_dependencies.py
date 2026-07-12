"""Composition provider for GraphRAG queue monitoring."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .adapters.redis_queue_monitor import (
    EmptyGraphRAGQueueMonitor,
    RedisGraphRAGQueueMonitor,
)
from .monitoring import GraphRAGQueueMonitor


@lru_cache
def get_graphrag_queue_monitor() -> GraphRAGQueueMonitor:
    if settings.ingest_queue_backend == "memory":
        return EmptyGraphRAGQueueMonitor()
    return RedisGraphRAGQueueMonitor(
        redis_url=settings.celery_broker_url or settings.redis_url,
    )
