"""Lightweight model-cache presence checks for container healthchecks."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .contracts.rag_defaults import (
    DEFAULT_FASTEMBED_CACHE_DIR,
    DEFAULT_FASTEMBED_DENSE_MODEL,
    DEFAULT_RERANKER_MODEL,
    DEFAULT_SPARSE_MODEL,
)
from .fastembed_cache import (
    RERANKER_REQUIRED_SNAPSHOT_FILES,
    has_complete_fastembed_model_cache,
    has_fastembed_model_cache,
    huggingface_cache_dir_names,
)

DEFAULT_FASTEMBED_CACHE_PATH = Path(DEFAULT_FASTEMBED_CACHE_DIR)
DEFAULT_DOCLING_CACHE_DIR = Path("/models/docling")


def verify_fastembed_cache(
    cache_dir: Path, *, dense_model: str, sparse_model: str, reranker_model: str
) -> None:
    missing: list[Path] = []
    for model_name in (dense_model, sparse_model):
        model_dirs = [
            cache_dir / cache_name
            for cache_name in huggingface_cache_dir_names(model_name)
        ]
        if not has_fastembed_model_cache(cache_dir, model_name):
            missing.append(model_dirs[0])
    reranker_dirs = [
        cache_dir / cache_name
        for cache_name in huggingface_cache_dir_names(reranker_model)
    ]
    if not has_complete_fastembed_model_cache(
        cache_dir,
        reranker_model,
        required_files=RERANKER_REQUIRED_SNAPSHOT_FILES,
    ):
        missing.append(reranker_dirs[0])
    if missing:
        _raise_missing("FastEmbed", cache_dir, missing)


def verify_docling_cache(cache_dir: Path) -> None:
    required = [
        cache_dir / "docling-project--docling-layout-heron",
        cache_dir / "docling-project--docling-models",
        cache_dir / "RapidOcr",
    ]
    missing = [path for path in required if not _is_nonempty_dir(path)]
    if missing:
        _raise_missing("Docling/OCR", cache_dir, missing)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fastembed", action="store_true")
    parser.add_argument("--docling", action="store_true")
    parser.add_argument(
        "--fastembed-cache-dir",
        type=Path,
        default=Path(
            os.getenv("RAG_RERANKER_CACHE_DIR")
            or os.getenv("RAG_SPARSE_CACHE_DIR")
            or DEFAULT_FASTEMBED_CACHE_PATH
        ),
    )
    parser.add_argument(
        "--docling-cache-dir",
        type=Path,
        default=Path(os.getenv("DOCLING_ARTIFACTS_PATH", DEFAULT_DOCLING_CACHE_DIR)),
    )
    parser.add_argument(
        "--sparse-model", default=_env_value("RAG_SPARSE_MODEL", DEFAULT_SPARSE_MODEL)
    )
    parser.add_argument(
        "--dense-model",
        default=_env_value("RAG_FASTEMBED_MODEL", DEFAULT_FASTEMBED_DENSE_MODEL),
    )
    parser.add_argument(
        "--reranker-model",
        default=_env_value("RAG_RERANKER_MODEL", DEFAULT_RERANKER_MODEL),
    )
    args = parser.parse_args()
    if not args.fastembed and not args.docling:
        parser.error("choose at least one of --fastembed or --docling")
    if args.fastembed:
        verify_fastembed_cache(
            args.fastembed_cache_dir,
            dense_model=args.dense_model,
            sparse_model=args.sparse_model,
            reranker_model=args.reranker_model,
        )
    if args.docling:
        verify_docling_cache(args.docling_cache_dir)


def _is_nonempty_dir(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def _raise_missing(label: str, cache_dir: Path, missing: list[Path]) -> None:
    preview = ", ".join(str(path) for path in missing)
    raise SystemExit(
        f"{label} model cache missing or invalid under {cache_dir}: {preview}"
    )


def _env_value(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


if __name__ == "__main__":
    main()
