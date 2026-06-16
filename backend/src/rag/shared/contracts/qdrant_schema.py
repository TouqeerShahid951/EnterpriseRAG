"""Qdrant collection schema contracts shared by RAG runtimes."""

from __future__ import annotations

from typing import Any

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
HYBRID_MODE = "hybrid"
LEGACY_DENSE_MODE = "legacy_dense"


def create_collection_payload(vector_size: int) -> dict[str, Any]:
    return {
        "vectors": {
            DENSE_VECTOR_NAME: {
                "size": vector_size,
                "distance": "Cosine",
            }
        },
        "sparse_vectors": {
            SPARSE_VECTOR_NAME: {},
        },
    }


def collection_mode(payload: dict[str, Any], vector_size: int) -> str | None:
    params = _collection_params(payload)
    vectors = params.get("vectors") if params else None
    if _named_dense_size(vectors) == vector_size and _has_sparse_vector(params):
        return HYBRID_MODE
    if _legacy_dense_size(vectors) == vector_size:
        return LEGACY_DENSE_MODE
    return None


def collection_vector_size(payload: dict[str, Any]) -> int | None:
    params = _collection_params(payload)
    vectors = params.get("vectors") if params else None
    return _named_dense_size(vectors) or _legacy_dense_size(vectors)


def _collection_params(payload: dict[str, Any]) -> dict[str, Any] | None:
    result = payload.get("result")
    config = result.get("config") if isinstance(result, dict) else None
    params = config.get("params") if isinstance(config, dict) else None
    return params if isinstance(params, dict) else None


def _named_dense_size(vectors: Any) -> int | None:
    dense = vectors.get(DENSE_VECTOR_NAME) if isinstance(vectors, dict) else None
    size = dense.get("size") if isinstance(dense, dict) else None
    return size if isinstance(size, int) else None


def _legacy_dense_size(vectors: Any) -> int | None:
    size = vectors.get("size") if isinstance(vectors, dict) else None
    return size if isinstance(size, int) else None


def _has_sparse_vector(params: dict[str, Any] | None) -> bool:
    sparse_vectors = params.get("sparse_vectors") if params else None
    return isinstance(sparse_vectors, dict) and SPARSE_VECTOR_NAME in sparse_vectors
