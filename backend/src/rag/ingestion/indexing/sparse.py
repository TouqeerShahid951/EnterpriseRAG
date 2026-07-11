"""Sparse text embeddings for worker-side Qdrant points."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from rag.shared.contracts.sparse import SparseVector
from rag.shared.runtime_offline import apply_runtime_offline_defaults

from ..adapters.http import ServiceRequestError


class SparseEmbedder:
    def __init__(self, *, model_name: str, cache_dir: str | None) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir

    def embed_many(self, texts: list[str]) -> list[SparseVector]:
        model = _load_sparse_model(self.model_name, self.cache_dir)
        try:
            vectors = [_coerce_sparse_vector(item) for item in model.embed(texts)]
        except Exception as exc:
            raise ServiceRequestError("sparse_embedder", f"sparse embedding failed: {exc}", 502) from exc
        if len(vectors) != len(texts):
            raise ServiceRequestError("sparse_embedder", "sparse model returned the wrong vector count", 502)
        return vectors


@lru_cache(maxsize=4)
def _load_sparse_model(model_name: str, cache_dir: str | None) -> Any:
    apply_runtime_offline_defaults()
    try:
        from fastembed import SparseTextEmbedding
    except ImportError as exc:
        raise ServiceRequestError(
            "sparse_embedder",
            "`fastembed` is required for sparse ingestion vectors",
            500,
        ) from exc
    return SparseTextEmbedding(model_name=model_name, cache_dir=cache_dir)


def _coerce_sparse_vector(value: Any) -> SparseVector:
    indices = _to_list(getattr(value, "indices", None))
    weights = _to_list(getattr(value, "values", None))
    if len(indices) != len(weights):
        raise ServiceRequestError("sparse_embedder", "sparse vector indices and values had different lengths", 502)
    return SparseVector(
        indices=[int(item) for item in indices],
        values=[float(item) for item in weights],
    )


def _to_list(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return converted if isinstance(converted, list) else []
    return value if isinstance(value, list) else []
