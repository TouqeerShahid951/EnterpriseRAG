"""Evidence deduplication, coverage scoring, and ordered selection."""

from __future__ import annotations

import hashlib
import re

from ..shared.contracts.evidence import SourceAnchor
from .qdrant import SearchHit
from .source_context_budget import _hits_within_budget
from .source_mapping import (
    _STOPWORDS,
    _normalized_text,
    _query_terms,
    payload_text,
    source_from_hit,
)
from .source_parent_promotion import _promote_parent_text

_EXACT_VALUE_RE = re.compile(
    r"\b(?:\d[\d,./:-]{1,}\d|[A-Za-z]+[A-Za-z0-9_-]*\d[A-Za-z0-9_-]*|\d[A-Za-z0-9_-]*[A-Za-z][A-Za-z0-9_-]*)\b"
)

_COVERAGE_STOPWORDS = _STOPWORDS | {
    "and",
    "are",
    "can",
    "could",
    "for",
    "has",
    "have",
    "into",
    "list",
    "listed",
    "show",
    "tell",
    "that",
    "this",
    "was",
    "were",
    "will",
    "with",
    "would",
}

COVERAGE_RESERVE_LIMIT = 3
COVERAGE_HEAD_LIMIT = 1
_STRUCTURED_QUERY_TERMS = {
    "amount",
    "column",
    "columns",
    "code",
    "date",
    "digit",
    "digits",
    "field",
    "fields",
    "form",
    "header",
    "id",
    "identifier",
    "job",
    "number",
    "numbers",
    "row",
    "rows",
    "sequence",
    "service",
    "table",
    "title",
    "total",
    "value",
}


def dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    seen: set[str] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        keys = _dedupe_keys(hit)
        if seen & keys:
            continue
        seen.update(keys)
        unique.append(hit)
    return unique


def build_evidence_hits(
    hits: list[SearchHit],
    *,
    token_budget: int,
    limit: int,
    broader_table_context: bool = False,
    query: str = "",
) -> list[SearchHit]:
    candidates = dedupe_hits(hits)
    if broader_table_context:
        candidates = dedupe_hits(_promote_parent_text(candidates))
    candidates = _with_coverage_reserve(candidates, query)
    return _hits_within_budget(candidates, token_budget=token_budget, limit=limit)


def sources_from_hits(hits: list[SearchHit], *, query: str = "") -> list[SourceAnchor]:
    return [
        source_from_hit(hit, query=query)
        for hit in dedupe_hits(hits)
        if payload_text(hit)
    ]


def _coverage_terms(query: str) -> list[str]:
    return [term for term in _query_terms(query) if term not in _COVERAGE_STOPWORDS]


def _with_coverage_reserve(hits: list[SearchHit], query: str) -> list[SearchHit]:
    terms = _coverage_terms(query)
    exact_values = _exact_values(query)
    if not terms and not exact_values:
        return hits

    scored: list[tuple[int, int, SearchHit]] = []
    wants_structured = any(term in _STRUCTURED_QUERY_TERMS for term in terms)
    for index, hit in enumerate(hits):
        score = _coverage_score(
            hit,
            terms=terms,
            exact_values=exact_values,
            wants_structured=wants_structured,
        )
        if score > 0:
            scored.append((score, index, hit))
    if not scored:
        return hits

    reserve = [
        hit
        for _, _, hit in sorted(scored, key=lambda item: (-item[0], item[1]))[
            :COVERAGE_RESERVE_LIMIT
        ]
    ]
    if not reserve:
        return hits

    ordered: list[SearchHit] = []
    seen: set[str] = set()

    def add(hit: SearchHit) -> None:
        key = str(hit.payload.get("chunk_id") or hit.point_id)
        if key in seen:
            return
        seen.add(key)
        ordered.append(hit)

    for hit in hits[:COVERAGE_HEAD_LIMIT]:
        add(hit)
    for hit in reserve:
        add(hit)
    for hit in hits[COVERAGE_HEAD_LIMIT:]:
        add(hit)
    return ordered


def _coverage_score(
    hit: SearchHit,
    *,
    terms: list[str],
    exact_values: list[str],
    wants_structured: bool,
) -> int:
    text = _coverage_text(hit)
    if not text:
        return 0

    compact_text = _compact_value_text(text)
    exact_matches = sum(
        1 for value in exact_values if _compact_value_text(value) in compact_text
    )
    specific_terms = [term for term in terms if term not in _STRUCTURED_QUERY_TERMS]
    specific_matches = sum(1 for term in specific_terms if _term_in_text(term, text))
    structured_matches = sum(
        1
        for term in terms
        if term in _STRUCTURED_QUERY_TERMS and _term_in_text(term, text)
    )

    if not exact_matches and not specific_matches and not structured_matches:
        return 0

    score = (
        exact_matches * 8 + min(specific_matches, 6) * 2 + min(structured_matches, 3)
    )
    if wants_structured and _is_structured_hit(hit):
        score += 4
    return score


def _coverage_text(hit: SearchHit) -> str:
    payload = hit.payload
    parts = [payload_text(hit)]
    for key in ("doc_title", "section_title", "heading", "table_title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    raw_fields = payload.get("structured_fields")
    if isinstance(raw_fields, list):
        for raw_field in raw_fields:
            if not isinstance(raw_field, dict):
                continue
            label = raw_field.get("label")
            value = raw_field.get("value")
            if isinstance(label, str):
                parts.append(label)
            if isinstance(value, str):
                parts.append(value)
    return _normalized_text(" ".join(parts))


def _is_structured_hit(hit: SearchHit) -> bool:
    payload = hit.payload
    if str(payload.get("structured_kind", "")) == "table_row":
        return True
    if str(payload.get("chunk_type", "")) in {
        "form",
        "form_field",
        "table",
        "table_row",
    }:
        return True
    raw_fields = payload.get("structured_fields")
    return isinstance(raw_fields, list) and bool(raw_fields)


def _exact_values(query: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for match in _EXACT_VALUE_RE.finditer(query):
        value = match.group(0).lower()
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _term_in_text(term: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE) is not None


def _compact_value_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _dedupe_keys(hit: SearchHit) -> set[str]:
    chunk_id = hit.payload.get("chunk_id") or hit.point_id
    keys = {f"chunk:{chunk_id}"}
    text = payload_text(hit)
    if text:
        keys.add(f"text:{hashlib.sha256(_normalized_text(text).encode()).hexdigest()}")
    for field in ("chunk_content_hash", "text_hash"):
        value = hit.payload.get(field)
        if isinstance(value, str) and value:
            keys.add(f"{field}:{value}")
    return keys
