"""Document-scope inference and fair cross-document ordering."""

from __future__ import annotations

import re

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from .qdrant import SearchHit
from .retrieval_hits import _doc_ids, _hit_doc_id, _hit_focus_tokens, _optional_int
from .routing_models import RoutePlan

_STRUCTURED_QUERY_STOPWORDS = {
    "all",
    "give",
    "list",
    "me",
    "number",
    "numbers",
    "of",
    "show",
    "the",
}
_EXHAUSTIVE_SCOPE_TOKENS = {
    "all",
    "complete",
    "each",
    "entire",
    "every",
    "full",
    "inventory",
    "list",
    "summaries",
    "summary",
    "summarize",
}
_DOCUMENT_SCOPE_STOPWORDS = _STRUCTURED_QUERY_STOPWORDS | {
    "a",
    "about",
    "across",
    "among",
    "an",
    "and",
    "any",
    "as",
    "brief",
    "by",
    "can",
    "commited",
    "committed",
    "could",
    "detail",
    "details",
    "do",
    "does",
    "done",
    "each",
    "entire",
    "every",
    "for",
    "from",
    "full",
    "in",
    "include",
    "including",
    "inside",
    "into",
    "on",
    "or",
    "over",
    "please",
    "provide",
    "summaries",
    "summarize",
    "summary",
    "tell",
    "that",
    "these",
    "this",
    "through",
    "to",
    "within",
    "with",
    "would",
    "you",
}
_BROAD_DOCUMENT_SCOPE_TOKENS = {
    "doc",
    "docs",
    "document",
    "documents",
    "file",
    "files",
    "source",
    "sources",
}
_DOCUMENT_SCOPE_FOCUS_STOPWORDS = (
    _DOCUMENT_SCOPE_STOPWORDS
    | _BROAD_DOCUMENT_SCOPE_TOKENS
    | {
        "activity",
        "activities",
        "are",
        "be",
        "been",
        "being",
        "did",
        "doing",
        "is",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
    }
)
_DOCUMENT_SCOPE_FIELDS = (
    "doc_title",
    "source_id",
    "generated_doc_type",
    "doc_type",
    "auto_doc_type",
    "file_name",
    "filename",
    "mime_type",
)


def _should_expand_document_scope(query: str, plan: RoutePlan | None) -> bool:
    if plan is None or plan.intent != "aggregation":
        return False
    tokens = normalized_match_tokens(query)
    return bool(tokens & _EXHAUSTIVE_SCOPE_TOKENS)


def _document_scope_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    target_doc_ids = _target_document_ids_for_scope(query, hits)
    if not target_doc_ids:
        return []
    scoped = [hit for hit in hits if _hit_doc_id(hit) in target_doc_ids]
    if _has_broad_document_scope(query):
        focused = _focused_document_scope_hits(query, scoped)
        if focused:
            scoped = focused
    return [_mark_document_scope_hit(hit) for hit in _round_robin_document_hits(scoped)]


def _target_document_ids_for_scope(query: str, hits: list[SearchHit]) -> set[str]:
    all_doc_ids = _doc_ids(hits)
    metadata_by_doc = _metadata_tokens_by_doc(hits)
    for tokens in _document_scope_token_groups(query):
        if not tokens:
            continue
        if tokens <= _BROAD_DOCUMENT_SCOPE_TOKENS:
            return all_doc_ids
        matched = _documents_matching_scope_tokens(
            tokens - _BROAD_DOCUMENT_SCOPE_TOKENS or tokens, metadata_by_doc
        )
        if matched:
            return matched
    return set()


def _document_scope_token_groups(query: str) -> list[set[str]]:
    groups: list[set[str]] = []
    lowered = query.lower()
    preposition_pattern = (
        r"\b(?:in|from|across|among|within|over|through|for|of)\s+(?:the\s+)?"
        r"((?:[a-z0-9][a-z0-9_-]*\s+){0,4}[a-z0-9][a-z0-9_-]*)"
    )
    exhaustive_pattern = (
        r"\b(?:all|every|each|entire|full)\s+(?:the\s+)?"
        r"((?:[a-z0-9][a-z0-9_-]*\s+){0,4}[a-z0-9][a-z0-9_-]*)"
    )
    for pattern in (preposition_pattern, exhaustive_pattern):
        for match in re.finditer(pattern, lowered):
            tokens = _scope_tokens(match.group(1))
            if tokens and tokens not in groups:
                groups.append(tokens)
    return groups


def _has_broad_document_scope(query: str) -> bool:
    return any(
        tokens and tokens <= _BROAD_DOCUMENT_SCOPE_TOKENS
        for tokens in _document_scope_token_groups(query)
    )


def _focused_document_scope_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    focus_tokens = _document_scope_focus_tokens(query)
    if not focus_tokens:
        return []
    scored = [
        (len(focus_tokens & _hit_focus_tokens(hit)), index, hit)
        for index, hit in enumerate(hits)
    ]
    matched = [(score, index, hit) for score, index, hit in scored if score > 0]
    if not matched:
        return []
    return [
        hit
        for _, _, hit in sorted(
            matched,
            key=lambda item: (-item[0], _document_scope_sort_key(item[2]), item[1]),
        )
    ]


def _document_scope_focus_tokens(query: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(query)
        if len(token) > 2 and token not in _DOCUMENT_SCOPE_FOCUS_STOPWORDS
    }


def _scope_tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(text)
        if len(token) > 2 and token not in _DOCUMENT_SCOPE_STOPWORDS
    }


def _documents_matching_scope_tokens(
    tokens: set[str], metadata_by_doc: dict[str, set[str]]
) -> set[str]:
    scored = {
        doc_id: len(tokens & metadata_tokens)
        for doc_id, metadata_tokens in metadata_by_doc.items()
        if tokens & metadata_tokens
    }
    if not scored:
        return set()
    best_score = max(scored.values())
    return {doc_id for doc_id, score in scored.items() if score == best_score}


def _metadata_tokens_by_doc(hits: list[SearchHit]) -> dict[str, set[str]]:
    metadata_by_doc: dict[str, set[str]] = {}
    for hit in hits:
        doc_id = _hit_doc_id(hit)
        metadata_by_doc.setdefault(doc_id, set()).update(_document_metadata_tokens(hit))
    return metadata_by_doc


def _document_metadata_tokens(hit: SearchHit) -> set[str]:
    tokens: set[str] = set()
    for field in _DOCUMENT_SCOPE_FIELDS:
        value = hit.payload.get(field)
        if isinstance(value, str):
            tokens.update(normalized_match_tokens(value))
    for field in ("tags", "document_tags"):
        value = hit.payload.get(field)
        if isinstance(value, list):
            tokens.update(
                token for item in value for token in normalized_match_tokens(item)
            )
    return tokens


def _mark_document_scope_hit(hit: SearchHit) -> SearchHit:
    payload = dict(hit.payload)
    payload["exhaustive_scope_origin"] = "document_class_scope"
    return SearchHit(point_id=hit.point_id, score=hit.score, payload=payload)


def _round_robin_document_hits(hits: list[SearchHit]) -> list[SearchHit]:
    grouped: dict[str, list[SearchHit]] = {}
    for hit in sorted(hits, key=_document_scope_sort_key):
        grouped.setdefault(_hit_doc_id(hit), []).append(hit)
    ordered: list[SearchHit] = []
    index = 0
    while True:
        added = False
        for doc_id in sorted(grouped):
            group = grouped[doc_id]
            if index < len(group):
                ordered.append(group[index])
                added = True
        if not added:
            return ordered
        index += 1


def _document_scope_sort_key(hit: SearchHit) -> tuple[str, int, int, str]:
    payload = hit.payload
    return (
        str(payload.get("doc_title") or payload.get("doc_id") or ""),
        _optional_int(payload.get("page_start"))
        or _optional_int(payload.get("page"))
        or 10**9,
        _optional_int(payload.get("table_row_index")) or 0,
        str(payload.get("chunk_id", hit.point_id)),
    )
