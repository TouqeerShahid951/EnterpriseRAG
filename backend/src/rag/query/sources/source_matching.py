"""Deterministic source directives, matching, and preference scoring."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from rag.query.sources.source_catalog import VisibleDocumentSource, VisibleQuerySource

PreferredSource = Literal["database", "corpus", "balanced"]

_DB_DIRECTIVE_RE = re.compile(
    r"\b(?:in|from|using|use|query|search)\s+(?:the\s+)?(?:live\s+)?(?:db|database)\b",
    flags=re.IGNORECASE,
)
_CORPUS_DIRECTIVE_RE = re.compile(
    r"\b(?:in|from|using|use|search)\s+(?:the\s+)?(?:docs?|documents?|corpus|knowledge\s+space|uploaded\s+docs?)\b",
    flags=re.IGNORECASE,
)
_STRUCTURED_TERMS = {
    "average",
    "count",
    "counts",
    "current",
    "filter",
    "group",
    "latest",
    "list",
    "maximum",
    "minimum",
    "oldest",
    "records",
    "rows",
    "show",
    "sort",
    "sum",
    "total",
    "totals",
}
_CORPUS_TERMS = {
    "according",
    "clause",
    "contract",
    "define",
    "describe",
    "document",
    "documents",
    "explain",
    "manual",
    "page",
    "policy",
    "procedure",
    "summarize",
    "summary",
}


@dataclass(frozen=True)
class _SourcePreference:
    preferred_source: PreferredSource
    confidence: float
    reason: str
    preferred_catalog_id: str | None = None
    router_mode: str = "deterministic"


def _strip_source_directive(query: str) -> tuple[str, str | None]:
    if _DB_DIRECTIVE_RE.search(query):
        return _compact_query(_DB_DIRECTIVE_RE.sub(" ", query)), "db"
    if _CORPUS_DIRECTIVE_RE.search(query):
        return _compact_query(_CORPUS_DIRECTIVE_RE.sub(" ", query)), "corpus"
    return query.strip(), None


def _inline_named_source(
    query: str, sources: list[VisibleQuerySource]
) -> VisibleQuerySource | None:
    normalized = _normalize(query)
    for source in sources:
        name = _normalize(source.name)
        if len(name) < 4:
            continue
        if (
            f"use {name}" in normalized
            or f"using {name}" in normalized
            or f"from {name}" in normalized
        ):
            return source
    return None


def _strip_named_source(query: str, source: VisibleQuerySource) -> str:
    name = re.escape(source.name)
    stripped = re.sub(
        rf"\b(?:use|using|from)\s+{name}\b", " ", query, flags=re.IGNORECASE
    )
    return _compact_query(stripped)


def _term_score(query: str, terms: set[str]) -> int:
    tokens = set(_tokens(query))
    return len(tokens & terms)


def _structured_score(query: str) -> int:
    tokens = set(_tokens(query))
    score = _term_score(query, _STRUCTURED_TERMS)
    lowered = f" {query.lower()} "
    if " by " in lowered and {"count", "sum", "total", "average"} & tokens:
        score += 1
    if re.search(r"\btop\s+\d+\b", query, flags=re.IGNORECASE):
        score += 1
    return score


def _source_match_score(query: str, source: VisibleQuerySource) -> int:
    query_tokens = set(_tokens(query))
    source_tokens = set(_tokens(source.match_text))
    return len(query_tokens & source_tokens)


def _document_match_score(query: str, document: VisibleDocumentSource) -> int:
    query_tokens = set(_tokens(query))
    document_tokens = set(_tokens(document.match_text))
    return len(query_tokens & document_tokens)


def _best_scored_source(
    scored: list[tuple[VisibleQuerySource, int]],
) -> VisibleQuerySource | None:
    if not scored:
        return None
    source, score = max(scored, key=lambda item: item[1])
    return source if score > 0 else None


def _deterministic_preference(
    *,
    structured_score: int,
    corpus_score: int,
    source_match_score: int,
    document_match_score: int,
    db_bias: int,
    corpus_bias: int,
) -> _SourcePreference:
    if document_match_score >= 2 and source_match_score == 0:
        return _SourcePreference(
            "corpus",
            0.90,
            f"strong_document_match={document_match_score},source_match=0",
        )
    db_score = source_match_score + (structured_score * 2) + db_bias
    doc_score = document_match_score + (corpus_score * 2) + corpus_bias
    margin = db_score - doc_score
    if margin >= 2:
        preferred: PreferredSource = "database"
    elif margin <= -2:
        preferred = "corpus"
    else:
        preferred = "balanced"
    total = max(1, db_score + doc_score)
    confidence = 0.5 + min(0.45, abs(margin) / max(4, total))
    reason = f"db_score={db_score},doc_score={doc_score},margin={margin}"
    return _SourcePreference(preferred, confidence, reason)


def _conversation_source_bias(turns: list[dict[str, object]]) -> tuple[int, int]:
    db_bias = 0
    corpus_bias = 0
    for turn in turns[-3:]:
        mode = str(turn.get("source_mode") or "")
        preferred = str(turn.get("preferred_source") or "")
        if mode in {"db_only", "db_first"} or preferred == "database":
            db_bias += 2
        elif mode == "corpus_only" or preferred == "corpus":
            corpus_bias += 2
        elif mode == "hybrid" or preferred == "balanced":
            db_bias += 1
            corpus_bias += 1
        for source in turn.get("sources") or []:
            if not isinstance(source, dict):
                continue
            doc_id = str(source.get("doc_id") or "")
            if doc_id.startswith("connector-live-scope:"):
                db_bias += 1
            elif doc_id:
                corpus_bias += 1
    return db_bias, corpus_bias


def _tokens(value: str) -> list[str]:
    return [
        match.group(0).lower()
        for match in re.finditer(r"[A-Za-z0-9_]{3,}", value)
    ]


def _normalize(value: str) -> str:
    return " ".join(_tokens(value))


def _compact_query(value: str) -> str:
    return " ".join(value.split()).strip()
