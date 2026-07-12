"""Redis-backed GraphRAG queue monitoring."""

from __future__ import annotations

from typing import Any

from ..monitoring import GraphRAGQueuedTaskRecord, parse_queued_graphrag_task


class EmptyGraphRAGQueueMonitor:
    """Queue monitor for the in-process test/development backend."""

    def queue_length(self, queue_name: str) -> int:
        _ = queue_name
        return 0

    def queued_tasks(
        self,
        queue_name: str,
        *,
        limit: int = 25,
    ) -> tuple[GraphRAGQueuedTaskRecord, ...]:
        _ = (queue_name, limit)
        return ()


class RedisGraphRAGQueueMonitor:
    def __init__(self, *, redis_url: str, client: Any | None = None) -> None:
        self._redis_url = redis_url
        self._client_override = client

    def queue_length(self, queue_name: str) -> int:
        return int(self._client().llen(queue_name))

    def queued_tasks(
        self,
        queue_name: str,
        *,
        limit: int = 25,
    ) -> tuple[GraphRAGQueuedTaskRecord, ...]:
        raw_items = self._client().lrange(queue_name, 0, max(0, limit - 1))
        return tuple(
            task
            for raw_item in raw_items
            if (task := parse_queued_graphrag_task(raw_item)) is not None
        )

    def _client(self) -> Any:
        if self._client_override is not None:
            return self._client_override
        from redis import Redis

        return Redis.from_url(self._redis_url, decode_responses=False)
