"""Definition-oriented recall expansion policy."""

from __future__ import annotations

import re

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from rag.query.qdrant import SearchHit
from rag.query.retrieval.retrieval_document_scope import _DOCUMENT_SCOPE_FOCUS_STOPWORDS
from rag.query.retrieval.retrieval_hits import _hit_focus_text

_RECALL_EXPANSION_STOPWORDS = _DOCUMENT_SCOPE_FOCUS_STOPWORDS | {
    "define",
    "defined",
    "defines",
    "definition",
    "how",
    "meaning",
    "mean",
    "means",
    "term",
    "terms",
}
_DEFINITION_CUES = (
    " defined as ",
    " definition ",
    " means ",
    " refers to ",
    " is defined as ",
    " is considered ",
    " is a ",
    " is an ",
    " is any ",
    " are defined as ",
    " are considered ",
    " are any ",
)
_DEFINITION_TARGET_PATTERNS = (
    re.compile(
        r"\bdefine[sd]?\s+(?:a|an|the|term\s+)?(?P<target>[a-z0-9][a-z0-9 _/-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmeaning\s+of\s+(?:a|an|the|term\s+)?(?P<target>[a-z0-9][a-z0-9 _/-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\s+does\s+(?:a|an|the|term\s+)?(?P<target>[a-z0-9][a-z0-9 _/-]{1,80})\s+mean\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<target>[a-z0-9][a-z0-9 _/-]{1,80})\s+(?:definition|meaning)\b",
        re.IGNORECASE,
    ),
)


def _recall_expansion_queries(query: str, hits: list[SearchHit]) -> list[str]:
    target = _definition_target(query)
    if not target or _has_definition_evidence(target, hits[:8]):
        return []
    target_variants = _target_variants(target)
    context = " ".join(_recall_context_terms(query, target))
    queries: list[str] = []
    if context:
        queries.append(f"{context} {target} definition")
    queries.append(f"{target} definition")
    queries.append(f"{target_variants[-1]} refers to")
    return _unique_nonempty(queries)[:3]


def _definition_target(query: str) -> str:
    lowered = query.lower()
    if not any(
        term in lowered for term in ("define", "definition", "meaning", " mean")
    ):
        return ""
    for pattern in _DEFINITION_TARGET_PATTERNS:
        match = pattern.search(query)
        if not match:
            continue
        target = re.split(
            r"\b(?:according|from|in|inside|within|under|for|on|per|as|context)\b",
            match.group("target").strip(" ?."),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        tokens = _ordered_recall_tokens(target)
        if tokens:
            return " ".join(tokens[:4])
    return ""


def _has_definition_evidence(target: str, hits: list[SearchHit]) -> bool:
    target_variants = _target_variants(target)
    for hit in hits:
        text = f" {_hit_focus_text(hit).lower()} "
        if any(
            _definition_cue_near_target(text, variant) for variant in target_variants
        ):
            return True
    return False


def _definition_cue_near_target(text: str, target: str) -> bool:
    tokens = normalized_match_tokens(target)
    if not tokens:
        return False
    for token in tokens:
        for match in re.finditer(rf"\b{re.escape(token)}\b", text):
            window = text[match.start() : match.end() + 180]
            if any(cue in window for cue in _DEFINITION_CUES):
                return True
    return False


def _recall_context_terms(query: str, target: str) -> list[str]:
    target_tokens = set(_ordered_recall_tokens(target))
    terms = [
        token
        for token in _ordered_recall_tokens(query)
        if len(token) > 2
        and token not in target_tokens
        and token not in _RECALL_EXPANSION_STOPWORDS
    ]
    return terms[:2]


def _ordered_recall_tokens(text: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for match in re.finditer(r"[a-z0-9][a-z0-9_-]{2,}", text.lower()):
        token = match.group(0)
        if token in seen or token in _RECALL_EXPANSION_STOPWORDS:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _target_variants(target: str) -> list[str]:
    variants = [target]
    tokens = target.split()
    if len(tokens) == 1 and tokens[0].endswith("s") and len(tokens[0]) > 3:
        variants.append(tokens[0][:-1])
    return variants


def _unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _annotate_recall_hits(
    hits: list[SearchHit], *, recall_query: str
) -> list[SearchHit]:
    annotated: list[SearchHit] = []
    for hit in hits:
        payload = dict(hit.payload)
        payload["recall_origin"] = "answer_type_expansion"
        payload["recall_query"] = recall_query
        annotated.append(
            SearchHit(point_id=hit.point_id, score=hit.score, payload=payload)
        )
    return annotated
