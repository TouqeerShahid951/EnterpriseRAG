"""Ports used by retrieval and query application code."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

T = TypeVar("T")


class VectorStore(Protocol):
    def prepare_for_query(self, vector_size: int) -> bool: ...

    def search_dense(self, *, vector: list[float], limit: int, qdrant_filter: dict[str, Any]) -> list[Any]: ...

    def search_hybrid(
        self,
        *,
        dense_vector: list[float],
        sparse_vector: object,
        limit: int,
        qdrant_filter: dict[str, Any],
    ) -> list[Any]: ...


class SparseIndex(Protocol):
    def embed_sparse(self, text: str) -> object: ...


class LanguageModel(Protocol):
    def answer(self, *args: Any, **kwargs: Any) -> str: ...


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class ObjectStorage(Protocol):
    def read(self, object_path: str) -> Any: ...

    def write(self, *, content: bytes, filename: str, content_type: str) -> Any: ...


class Repository(Protocol[T]):
    def get(self, identifier: str) -> T | None: ...
