"""Ports owned by the ingestion service."""

from __future__ import annotations

from typing import Any, Protocol


class IngestionStatusReporter(Protocol):
    def update_job(self, *, job_id: str, status: str, progress_pct: int, **kwargs: Any) -> Any: ...


class IngestionObjectStorage(Protocol):
    def read(self, object_path: str) -> bytes: ...


class IngestionVectorIndex(Protocol):
    def upsert_points(self, points: list[dict[str, Any]]) -> Any: ...


class IngestionEmbedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
