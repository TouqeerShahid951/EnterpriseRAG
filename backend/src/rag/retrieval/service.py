"""Stable retrieval entrypoint used by the query workflow."""

from __future__ import annotations

from typing import Any

from rag.core.config import Settings
from rag.query.state import QueryContext
from rag.query.query_retrieval import retrieve_candidates


class RetrievalService:
    """Coordinate query-time retrieval behind one application-facing API."""

    def __init__(self, *, config: Settings, embedder: Any, vector_store: Any) -> None:
        self._config = config
        self._embedder = embedder
        self._vector_store = vector_store

    def retrieve(self, ctx: QueryContext) -> list[Any]:
        return retrieve_candidates(
            ctx,
            config=self._config,
            ollama=self._embedder,
            qdrant=self._vector_store,
        )
