"""Cross-encoder reranking for retrieved chunks."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from rag.shared.contracts.structured_payloads import (
    normalized_match_tokens,
    normalized_phrase,
    normalized_tokens,
)
from rag.shared.contracts.reranker_models import DEFAULT_RERANKER_MODEL
from rag.shared.runtime_offline import apply_runtime_offline_defaults

from .qdrant import SearchHit
from .metadata_scoring import annotate_metadata_matches, metadata_score

_FIELD_LABEL_SEPARATOR_RE = re.compile(r"[|\n]")
_LOG = logging.getLogger(__name__)
_RERANK_STATUS_SCORED = "scored"
_RERANK_STATUS_FALLBACK = "fallback"
_STOPWORDS = {
    "about",
    "after",
    "before",
    "does",
    "from",
    "have",
    "into",
    "that",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}


def rerank_hits(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    max_candidates: int | None = None,
    model_name: str = DEFAULT_RERANKER_MODEL,
    cache_dir: str | None = "/models/fastembed",
) -> list[SearchHit]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if max_candidates is not None and max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    return _cross_encoder_rerank(
        query,
        hits,
        top_k=top_k,
        max_candidates=max_candidates,
        model_name=model_name,
        cache_dir=cache_dir,
    )


def rank_passages(
    query: str,
    passages: list[str],
    *,
    model_name: str = DEFAULT_RERANKER_MODEL,
    cache_dir: str | None = "/models/fastembed",
) -> list[tuple[int, float]]:
    if not model_name:
        raise ValueError("cross-encoder reranker model name is required")
    if not passages:
        return []
    model = _load_cross_encoder(model_name, cache_dir)
    scores = [float(score) for score in model.rerank(query, passages)]
    if len(scores) != len(passages):
        raise RuntimeError("cross-encoder reranker returned an unexpected score count")
    return sorted(enumerate(scores), key=lambda item: (-item[1], item[0]))


def _cross_encoder_rerank(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    max_candidates: int | None,
    model_name: str,
    cache_dir: str | None,
) -> list[SearchHit]:
    if not model_name:
        raise ValueError("cross-encoder reranker model name is required")
    if not hits:
        return []
    hits = annotate_metadata_matches(query, hits)
    hits = _limit_rerank_candidates(query, hits, max_candidates=max_candidates)
    try:
        model = _load_cross_encoder(model_name, cache_dir)
        scores = model.rerank(query, [_searchable_text(hit) for hit in hits])
        score_values = [float(score) for score in scores]
        if len(score_values) != len(hits):
            raise RuntimeError("cross-encoder reranker returned an unexpected score count")
    except Exception as exc:
        _LOG.warning(
            "cross-encoder reranker failed; falling back to retrieval policy",
            extra={
                "candidate_count": len(hits),
                "error_type": type(exc).__name__,
                "model_name": model_name,
            },
            exc_info=True,
        )
        return _fallback_rank_hits(query, hits, top_k=top_k, error=exc)
    scored_hits = [
        SearchHit(
            point_id=hit.point_id,
            score=hit.score,
            payload={
                **hit.payload,
                "_rerank_score": score,
                "_rerank_status": _RERANK_STATUS_SCORED,
                "_rerank_candidate_count": len(hits),
            },
        )
        for hit, score in zip(hits, score_values, strict=True)
    ]
    ranked = sorted(
        enumerate(zip(scored_hits, score_values, strict=True)),
        key=lambda item: (-item[1][1], -metadata_score(item[1][0]), item[0]),
    )
    ranked = _promote_table_field_label_matches(query, ranked)
    return [hit for _, (hit, _) in ranked[:top_k]]


def _limit_rerank_candidates(
    query: str,
    hits: list[SearchHit],
    *,
    max_candidates: int | None,
) -> list[SearchHit]:
    if max_candidates is None or len(hits) <= max_candidates:
        return hits
    retrieval_head = hits[:max(1, max_candidates // 4)]
    query_tokens = _tokens(query)
    ranked = sorted(
        enumerate(hits),
        key=lambda item: (
            _table_field_label_priority(query, item[1]),
            -len(query_tokens & _tokens(_searchable_text(item[1]))),
            -metadata_score(item[1]),
            _structured_origin_priority(item[1]),
            -item[1].score,
            item[0],
        ),
    )
    selected = _unique_hits(retrieval_head)
    seen = {_hit_identity(hit) for hit in selected}
    for _, hit in ranked:
        key = _hit_identity(hit)
        if key in seen:
            continue
        selected.append(hit)
        seen.add(key)
        if len(selected) >= max_candidates:
            break
    return selected


def _fallback_rank_hits(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    error: Exception,
) -> list[SearchHit]:
    query_tokens = _tokens(query)
    ranked = sorted(
        enumerate(hits),
        key=lambda item: (
            _table_field_label_priority(query, item[1]),
            -len(query_tokens & _tokens(_searchable_text(item[1]))),
            -metadata_score(item[1]),
            _structured_origin_priority(item[1]),
            -item[1].score,
            item[0],
        ),
    )
    fallback_ranked = [
        (
            original_index,
            (
                SearchHit(
                    point_id=hit.point_id,
                    score=hit.score,
                    payload={
                        **hit.payload,
                        "_rerank_status": _RERANK_STATUS_FALLBACK,
                        "_rerank_error": type(error).__name__,
                        "_rerank_candidate_count": len(hits),
                    },
                ),
                hit.score,
            ),
        )
        for original_index, hit in ranked
    ]
    fallback_ranked = _promote_table_field_label_matches(query, fallback_ranked)
    return [hit for _, (hit, _) in fallback_ranked[:top_k]]


def _unique_hits(hits: list[SearchHit]) -> list[SearchHit]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        key = _hit_identity(hit)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _hit_identity(hit: SearchHit) -> tuple[str, str, str]:
    return (
        str(hit.payload.get("doc_id", "")),
        str(hit.payload.get("chunk_id", hit.point_id)),
        hit.point_id,
    )


def _structured_origin_priority(hit: SearchHit) -> int:
    origin = hit.payload.get("structured_origin")
    if origin == "direct":
        return 0
    if origin == "sibling":
        return 2
    return 1


@lru_cache(maxsize=4)
def _load_cross_encoder(model_name: str, cache_dir: str | None) -> Any:
    apply_runtime_offline_defaults()
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError as exc:
        raise RuntimeError(
            "FastEmbed cross-encoder reranker requires optional dependency "
            "`fastembed`; install backend dependencies before running RAG queries"
        ) from exc
    return TextCrossEncoder(model_name=model_name, cache_dir=cache_dir)


def _searchable_text(hit: SearchHit) -> str:
    payload = hit.payload
    parts: list[str] = []
    structured_search_text = payload.get("structured_search_text")
    if isinstance(structured_search_text, str) and structured_search_text.strip():
        parts.append(structured_search_text)
    for key in (
        "doc_title",
        "doc_summary",
        "text",
        "summary",
        "table_title",
        "table_caption",
        "table_row_label",
        "section_title",
        "generated_doc_type",
        "doc_type",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    headers = payload.get("table_column_headers")
    if isinstance(headers, list):
        parts.extend(str(header) for header in headers)
    section_path = payload.get("section_path")
    if isinstance(section_path, list):
        parts.extend(str(part) for part in section_path)
    topics = payload.get("topics")
    if isinstance(topics, list):
        parts.extend(str(topic) for topic in topics)
    llm_topics = payload.get("llm_topics")
    if isinstance(llm_topics, list):
        parts.extend(str(topic) for topic in llm_topics)
    metadata_terms = payload.get("metadata_terms")
    if isinstance(metadata_terms, list):
        parts.extend(str(term) for term in metadata_terms)
    return " ".join(parts)


def _promote_table_field_label_matches(
    query: str,
    ranked: list[tuple[int, tuple[SearchHit, float]]],
) -> list[tuple[int, tuple[SearchHit, float]]]:
    if not ranked:
        return ranked
    priorities = [_table_field_label_priority(query, hit) for _, (hit, _) in ranked]
    if all(priority == 2 for priority in priorities):
        return ranked
    ordered = sorted(
        enumerate(ranked),
        key=lambda item: (priorities[item[0]], item[0]),
    )
    return [ranked_item for _, ranked_item in ordered]


def _table_field_label_priority(query: str, hit: SearchHit) -> int:
    query_tokens = _match_tokens(query)
    if not query_tokens:
        return 2
    best_priority = 2
    for label in _candidate_table_field_labels(hit):
        label_tokens = _match_tokens(label)
        if len(label_tokens) < 2 or not label_tokens <= query_tokens:
            continue
        if _normalized_phrase(label) in _normalized_query_phrases(query):
            return 0
        best_priority = min(best_priority, 1)
    return best_priority


def _candidate_table_field_labels(hit: SearchHit) -> list[str]:
    payload = hit.payload
    labels: list[str] = []
    structured_fields = payload.get("structured_fields")
    if isinstance(structured_fields, list):
        for field in structured_fields:
            if not isinstance(field, dict):
                continue
            label = field.get("label")
            if isinstance(label, str) and label.strip():
                labels.append(label.strip())
    row_label = payload.get("table_row_label")
    if isinstance(row_label, str) and row_label.strip():
        labels.append(row_label.strip())
    text = payload.get("text")
    if not isinstance(text, str):
        return labels
    for segment in _FIELD_LABEL_SEPARATOR_RE.split(text):
        label, separator, _ = segment.partition(":")
        label = label.strip().strip("[]")
        if separator and 2 <= len(label) <= 80:
            labels.append(label)
    return _unique_labels(labels)


def _unique_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for label in labels:
        normalized = _normalized_phrase(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(label)
    return unique


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_tokens(text)
        if len(token) > 2 and token not in _STOPWORDS
    }


def _match_tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(text)
        if len(token) > 2 and token not in _STOPWORDS
    }


def _normalized_phrase(text: str) -> str:
    return normalized_phrase(text)


def _normalized_query_phrases(query: str) -> set[str]:
    tokens = [token for token in normalized_phrase(query).split() if token]
    phrases: set[str] = set()
    for size in range(2, min(6, len(tokens)) + 1):
        phrases.update(" ".join(tokens[index : index + size]) for index in range(0, len(tokens) - size + 1))
    return phrases
