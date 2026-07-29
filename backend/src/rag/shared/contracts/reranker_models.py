"""Supported local cross-encoder reranker models."""

from __future__ import annotations

from .rag_defaults import DEFAULT_RERANKER_MODEL

SUPPORTED_RERANKER_MODELS = (
    "jinaai/jina-reranker-v1-turbo-en",
    "jinaai/jina-reranker-v1-tiny-en",
    "BAAI/bge-reranker-base",
    "Xenova/ms-marco-MiniLM-L-12-v2",
    "Xenova/ms-marco-MiniLM-L-6-v2",
)

_SHORT_CONTEXT_PASSAGE_MAX_CHARS = 1_400
_LONG_CONTEXT_PASSAGE_MAX_CHARS = 4_000


def normalize_reranker_model(value: str | None) -> str:
    candidate = (value or DEFAULT_RERANKER_MODEL).strip()
    return candidate or DEFAULT_RERANKER_MODEL


def is_supported_reranker_model(value: str | None) -> bool:
    return normalize_reranker_model(value) in SUPPORTED_RERANKER_MODELS


def reranker_passage_max_chars(value: str | None) -> int:
    model = normalize_reranker_model(value)
    return (
        _LONG_CONTEXT_PASSAGE_MAX_CHARS
        if model.startswith("jinaai/jina-reranker-v1-")
        else _SHORT_CONTEXT_PASSAGE_MAX_CHARS
    )
