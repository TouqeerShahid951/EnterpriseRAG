"""Download or verify FastEmbed dense, sparse, and reranker models."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from rag.shared.contracts.rag_defaults import (
    DEFAULT_FASTEMBED_CACHE_DIR,
    DEFAULT_FASTEMBED_DENSE_MODEL,
    DEFAULT_RERANKER_MODEL,
    DEFAULT_SPARSE_MODEL,
)
from rag.shared.contracts.reranker_models import SUPPORTED_RERANKER_MODELS
from rag.shared.runtime_offline import apply_runtime_offline_defaults

DEFAULT_FASTEMBED_CACHE_PATH = Path(DEFAULT_FASTEMBED_CACHE_DIR)


def prewarm_fastembed_models(
    *,
    dense_model: str,
    sparse_model: str,
    reranker_models: list[str],
    dense_cache_dir: Path,
    sparse_cache_dir: Path,
    reranker_cache_dir: Path,
) -> None:
    # Airgap bundles are commonly extracted on filesystems that cannot preserve
    # Hugging Face snapshot symlinks. Store portable regular files instead.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    apply_runtime_offline_defaults()
    _load_dense_model(dense_model, dense_cache_dir)
    _load_sparse_model(sparse_model, sparse_cache_dir)
    for reranker_model in reranker_models:
        _load_reranker_model(reranker_model, reranker_cache_dir)


def _load_dense_model(model_name: str, cache_dir: Path) -> Any:
    try:
        from fastembed import TextEmbedding

        model = TextEmbedding(model_name, cache_dir=str(cache_dir))
        vectors = list(model.embed(["airgap dense verification"]))
        if len(vectors) != 1:
            raise RuntimeError("dense probe returned an unexpected vector count")
        return model
    except Exception as exc:
        raise RuntimeError(
            f"FastEmbed dense model {model_name!r} is unavailable in cache {cache_dir}. "
            "Seed model-cache/fastembed while connected."
        ) from exc


def _load_sparse_model(model_name: str, cache_dir: Path) -> Any:
    try:
        from fastembed import SparseTextEmbedding

        model = SparseTextEmbedding(model_name, cache_dir=str(cache_dir))
        next(model.embed(["airgap sparse verification"]))
        return model
    except Exception as exc:
        raise RuntimeError(
            f"FastEmbed sparse model {model_name!r} is unavailable in cache {cache_dir}. "
            "Seed model-cache/fastembed while connected."
        ) from exc


def _load_reranker_model(model_name: str, cache_dir: Path) -> Any:
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        model = TextCrossEncoder(model_name=model_name, cache_dir=str(cache_dir))
        scores = model.rerank(
            "airgap reranker verification", ["airgap reranker verification"]
        )
        if len(list(scores)) != 1:
            raise RuntimeError("reranker probe returned an unexpected score count")
        return model
    except Exception as exc:
        raise RuntimeError(
            f"FastEmbed reranker model {model_name!r} is unavailable in cache {cache_dir}. "
            "Seed model-cache/fastembed while connected."
        ) from exc


def _env_value(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value) if value else default


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dense-model",
        default=_env_value("RAG_FASTEMBED_MODEL", DEFAULT_FASTEMBED_DENSE_MODEL),
    )
    parser.add_argument(
        "--sparse-model", default=_env_value("RAG_SPARSE_MODEL", DEFAULT_SPARSE_MODEL)
    )
    parser.add_argument(
        "--reranker-model",
        action="append",
        help="FastEmbed reranker model to download or verify. Can be repeated.",
    )
    parser.add_argument(
        "--all-rerankers",
        action="store_true",
        help="Download or verify every supported local reranker model.",
    )
    parser.add_argument(
        "--dense-cache-dir",
        type=Path,
        default=_env_path("RAG_DENSE_CACHE_DIR", DEFAULT_FASTEMBED_CACHE_PATH),
    )
    parser.add_argument(
        "--sparse-cache-dir",
        type=Path,
        default=_env_path("RAG_SPARSE_CACHE_DIR", DEFAULT_FASTEMBED_CACHE_PATH),
    )
    parser.add_argument(
        "--reranker-cache-dir",
        type=Path,
        default=_env_path("RAG_RERANKER_CACHE_DIR", DEFAULT_FASTEMBED_CACHE_PATH),
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate the local cache without downloading.",
    )
    args = parser.parse_args()
    if args.verify_only:
        os.environ.setdefault("AIRGAP_RUNTIME_OFFLINE", "1")
    reranker_models = (
        list(SUPPORTED_RERANKER_MODELS)
        if args.all_rerankers
        else args.reranker_model
        or [_env_value("RAG_RERANKER_MODEL", DEFAULT_RERANKER_MODEL)]
    )
    prewarm_fastembed_models(
        dense_model=args.dense_model,
        sparse_model=args.sparse_model,
        reranker_models=reranker_models,
        dense_cache_dir=args.dense_cache_dir,
        sparse_cache_dir=args.sparse_cache_dir,
        reranker_cache_dir=args.reranker_cache_dir,
    )
    action = "verified" if args.verify_only else "downloaded and verified"
    reranker_label = (
        "all supported rerankers" if args.all_rerankers else ", ".join(reranker_models)
    )
    print(
        "FastEmbed dense/sparse/reranker models "
        f"{action}: dense={args.dense_model} in {args.dense_cache_dir}; "
        f"sparse={args.sparse_model} in {args.sparse_cache_dir}; rerankers={reranker_label} in {args.reranker_cache_dir}"
    )


if __name__ == "__main__":
    main()
