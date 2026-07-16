"""Deterministic scoring, fallback, and structured-label ranking policies."""

from __future__ import annotations

import re

from rag.query.retrieval.metadata_scoring import (
    annotate_low_value_chunk,
    low_value_penalty_score,
    metadata_score,
    topic_score,
)
from ..qdrant import SearchHit
from .text import (
    hit_identity,
    match_tokens,
    normalized_query_phrases,
    normalized_text,
    searchable_text,
    tokens,
    unique_hits,
)

_FIELD_LABEL_SEPARATOR_RE = re.compile(r"[|\n]")
_RERANK_STATUS_SCORED = "scored"
_RERANK_STATUS_FALLBACK = "fallback"


def rank_scored_hits(
    query: str,
    hits: list[SearchHit],
    scores: list[float],
    *,
    top_k: int,
) -> list[SearchHit]:
    scored_hits = [
        annotate_low_value_chunk(
            query,
            SearchHit(
                point_id=hit.point_id,
                score=hit.score,
                payload={
                    **hit.payload,
                    "_rerank_score": score,
                    "_rerank_status": _RERANK_STATUS_SCORED,
                    "_rerank_candidate_count": len(hits),
                },
            ),
            rerank_score=score,
        )
        for hit, score in zip(hits, scores, strict=True)
    ]
    ranked = sorted(
        enumerate(zip(scored_hits, scores, strict=True)),
        key=lambda item: (
            -_rerank_sort_score(item[1][0], item[1][1]),
            -metadata_score(item[1][0]),
            -topic_score(item[1][0]),
            item[0],
        ),
    )
    ranked = _promote_table_field_label_matches(query, ranked)
    return [hit for _, (hit, _) in ranked[:top_k]]


def limit_rerank_candidates(
    query: str,
    hits: list[SearchHit],
    *,
    max_candidates: int | None,
) -> list[SearchHit]:
    if max_candidates is None or len(hits) <= max_candidates:
        return hits
    retrieval_head = hits[: max(1, max_candidates // 4)]
    query_tokens = tokens(query)
    ranked = sorted(
        enumerate(hits),
        key=lambda item: (
            _table_field_label_priority(query, item[1]),
            -len(query_tokens & tokens(searchable_text(item[1]))),
            -metadata_score(item[1]),
            -topic_score(item[1]),
            _structured_origin_priority(item[1]),
            -item[1].score,
            item[0],
        ),
    )
    selected = unique_hits(retrieval_head)
    seen = {hit_identity(hit) for hit in selected}
    for _, hit in ranked:
        key = hit_identity(hit)
        if key in seen:
            continue
        selected.append(hit)
        seen.add(key)
        if len(selected) >= max_candidates:
            break
    return selected


def fallback_rank_hits(
    query: str,
    hits: list[SearchHit],
    *,
    top_k: int,
    error: Exception,
) -> list[SearchHit]:
    query_tokens = tokens(query)
    annotated_hits = [annotate_low_value_chunk(query, hit) for hit in hits]
    ranked = sorted(
        enumerate(annotated_hits),
        key=lambda item: (
            _table_field_label_priority(query, item[1]),
            -len(query_tokens & tokens(searchable_text(item[1]))),
            -metadata_score(item[1]),
            -topic_score(item[1]),
            _structured_origin_priority(item[1]),
            -item[1].score,
            low_value_penalty_score(item[1]),
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


def _rerank_sort_score(hit: SearchHit, raw_score: float) -> float:
    value = hit.payload.get("_rerank_adjusted_score")
    return float(value) if isinstance(value, int | float) else raw_score


def _structured_origin_priority(hit: SearchHit) -> int:
    origin = hit.payload.get("structured_origin")
    if origin == "direct":
        return 0
    if origin == "sibling":
        return 2
    return 1


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
    query_tokens = match_tokens(query)
    if not query_tokens:
        return 2
    best_priority = 2
    for label in _candidate_table_field_labels(hit):
        label_tokens = match_tokens(label)
        if len(label_tokens) < 2 or not label_tokens <= query_tokens:
            continue
        if normalized_text(label) in normalized_query_phrases(query):
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
        normalized = normalized_text(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(label)
    return unique
