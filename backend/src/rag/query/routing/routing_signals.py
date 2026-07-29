"""Query normalization and signal extraction for intent routing."""

from __future__ import annotations

import re

from rag.query.routing.routing_models import QuerySignals

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}(?:-\d{2}){0,2}\b")
_RELATIVE_DATE_RE = re.compile(
    r"\b(?:q[1-4](?:\s+(?:19|20)\d{2})?|(?:last|previous|prior|first|second|third|fourth)\s+quarter|"
    r"last\s+(?:month|year)|at\s+the\s+time|(?:former|prior|earlier)\s+version)\b",
    re.IGNORECASE,
)
_FOLLOWUP_RE = re.compile(
    r"\b(it|that|those|they|them|previous answer|above|same|what about|how about|and for)\b",
    re.IGNORECASE,
)
_QUESTION_START_RE = re.compile(r"^(what|who|where|when|which|why|how|does|do|did|can|should|is|are)\b")
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")
_QUOTED_RE = re.compile(r"['\"]([^'\"]{2,80})['\"]")
_STOPWORDS = {
    "about",
    "after",
    "before",
    "between",
    "does",
    "from",
    "have",
    "into",
    "latest",
    "policy",
    "procedure",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}


def extract_query_signals(query: str, turns: list[dict[str, object]]) -> QuerySignals:
    original = query
    normalized = normalize_query(query)
    tokens = tuple(match.group(0).lower() for match in _TOKEN_RE.finditer(normalized))
    temporal_clues = tuple(_temporal_clues(normalized))
    followup_clues = list(match.group(0).lower() for match in _FOLLOWUP_RE.finditer(normalized))
    if turns:
        for demonstrative in ("this", "these"):
            if re.search(rf"\b{demonstrative}\b", normalized):
                followup_clues.append(demonstrative)
    if turns and len(tokens) <= 3 and temporal_clues:
        followup_clues.extend(temporal_clues)
    is_vague_followup = bool(followup_clues) and len(tokens) <= 8
    domain_clues = tuple(_domain_entity_clues(original, tokens))
    return QuerySignals(
        original_query=original,
        normalized_query=normalized,
        resolved_query=original.strip(),
        tokens=tokens,
        domain_entity_clues=domain_clues,
        temporal_clues=temporal_clues,
        followup_clues=tuple(_unique(followup_clues)),
        has_session_context=bool(turns),
        use_conversation_memory=False,
        is_short_query=len(tokens) <= 2,
        is_vague_followup=is_vague_followup,
        clarity_bonus=_has_clarity(normalized, tokens),
    )


def normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _temporal_clues(normalized: str) -> list[str]:
    clues = _DATE_RE.findall(normalized)
    clues.extend(match.group(0).lower() for match in _RELATIVE_DATE_RE.finditer(normalized))
    for phrase in (
        "latest",
        "current",
        "currently",
        "as of",
        "historical",
        "previous",
        "old",
        "before",
        "after",
        "still valid",
        "valid",
        "changed",
        "updated",
        "update",
        "version",
    ):
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized):
            clues.append(phrase)
    return sorted(set(clues))


def _domain_entity_clues(original: str, tokens: tuple[str, ...]) -> list[str]:
    clues: list[str] = []
    clues.extend(_ACRONYM_RE.findall(original))
    clues.extend(match.group(1).strip() for match in _QUOTED_RE.finditer(original))
    content_terms = [token for token in tokens if len(token) >= 4 and token not in _STOPWORDS]
    if len(content_terms) >= 2:
        clues.extend(content_terms[:4])
    return _unique(clues)


def _has_clarity(normalized: str, tokens: tuple[str, ...]) -> bool:
    if len(tokens) >= 4 and _QUESTION_START_RE.search(normalized):
        return True
    if re.search(r"^(define|explain|summarize|compare|list|show|find|open|walk|give)\b", normalized):
        return len(tokens) >= 3
    return len(tokens) >= 5 and any(term in normalized for term in ("compare", "summarize", "list", "show", "find", "open"))


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(value.strip())
    return unique
