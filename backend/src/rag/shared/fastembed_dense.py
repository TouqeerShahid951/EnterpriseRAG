"""Shared local dense embedding helpers backed by FastEmbed."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .runtime_offline import apply_runtime_offline_defaults

DEFAULT_FASTEMBED_DENSE_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q"
DEFAULT_FASTEMBED_CACHE_DIR = "/models/fastembed"


class FastEmbedDenseError(RuntimeError):
    """Raised when local dense FastEmbed vectors cannot be generated."""


def list_supported_dense_models(*, cache_dir: str | None = None, cached_only: bool = False) -> list[str]:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise FastEmbedDenseError("`fastembed` is required for local dense embeddings") from exc
    models = _supported_model_sources(TextEmbedding.list_supported_models())
    if cached_only:
        models = {
            model: source
            for model, source in models.items()
            if has_fastembed_model_cache(cache_dir or DEFAULT_FASTEMBED_CACHE_DIR, source)
        }
    return sorted(models)


def has_fastembed_model_cache(cache_dir: str | None, model_name: str) -> bool:
    if not cache_dir or not model_name.strip():
        return False
    root = Path(cache_dir)
    return any(_has_snapshot(root / cache_name) for cache_name in _huggingface_cache_dir_names(model_name))


def _supported_model_sources(models: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        name = str(model.get("model", "")).strip()
        if not name:
            continue
        sources = model.get("sources")
        hf_source = sources.get("hf") if isinstance(sources, dict) else None
        result[name] = str(hf_source or name).strip()
    return result


def _huggingface_cache_dir_names(model_name: str) -> list[str]:
    normalized = model_name.strip()
    names = [_huggingface_cache_dir_name(normalized)]
    if normalized.endswith("-Q"):
        names.append(_huggingface_cache_dir_name(normalized.removesuffix("-Q")))
    return names


def _huggingface_cache_dir_name(model_name: str) -> str:
    return "models--" + model_name.replace("/", "--")


def _has_snapshot(path: Path) -> bool:
    snapshots = path / "snapshots"
    return path.is_dir() and snapshots.is_dir() and any(snapshots.iterdir())


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
