"""Shared local dense embedding helpers backed by FastEmbed."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .runtime_offline import apply_runtime_offline_defaults

DEFAULT_FASTEMBED_DENSE_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q"
DEFAULT_FASTEMBED_CACHE_DIR = "/models/fastembed"


class FastEmbedDenseError(RuntimeError):
    """Raised when local dense FastEmbed vectors cannot be generated."""


def list_supported_dense_models() -> list[str]:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise FastEmbedDenseError("`fastembed` is required for local dense embeddings") from exc
    return sorted(
        {
            str(model.get("model", "")).strip()
            for model in TextEmbedding.list_supported_models()
            if isinstance(model, dict) and str(model.get("model", "")).strip()
        }
    )


def embed_dense_texts(
    texts: list[str],
    *,
    model_name: str,
    cache_dir: str | None,
    batch_size: int = 256,
) -> list[list[float]]:
    if not texts:
        return []
    model = _load_dense_model(model_name, cache_dir)
    try:
        vectors = [_coerce_dense_vector(item) for item in model.embed(texts, batch_size=max(1, batch_size))]
    except Exception as exc:
        raise FastEmbedDenseError(f"local dense embedding failed: {exc}") from exc
    if len(vectors) != len(texts):
        raise FastEmbedDenseError("local dense model returned the wrong vector count")
    return vectors


@lru_cache(maxsize=4)
def _load_dense_model(model_name: str, cache_dir: str | None) -> Any:
    apply_runtime_offline_defaults()
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise FastEmbedDenseError("`fastembed` is required for local dense embeddings") from exc
    try:
        return TextEmbedding(model_name=model_name, cache_dir=cache_dir)
    except Exception as exc:
        raise FastEmbedDenseError(f"could not load FastEmbed model {model_name!r}: {exc}") from exc


def _coerce_dense_vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list) or not value:
        raise FastEmbedDenseError("local dense model did not return a vector")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise FastEmbedDenseError("local dense vector contained non-numeric values") from exc
