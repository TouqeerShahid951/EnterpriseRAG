"""Deterministic evidence-quality signals for retrieval verification."""

from __future__ import annotations

from dataclasses import dataclass

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from .qdrant import SearchHit

STRONG_RETRIEVAL_SCORE = 0.6
SUPPORTED_TOKEN_COVERAGE = 0.5
PARTIAL_TOKEN_COVERAGE = 0.25

_QUERY_STOPWORDS = {
    "and",
    "about",
    "are",
    "answer",
    "can",
    "citation",
    "citations",
    "compare",
    "could",
    "describe",
    "does",
    "document",
    "documents",
    "evidence",
    "explain",
    "find",
    "for",
    "from",
    "give",
    "has",
    "have",
    "how",
    "list",
    "manual",
    "may",
    "of",
    "on",
    "please",
    "policy",
    "question",
    "should",
    "show",
    "source",
    "sources",
    "summarize",
    "summary",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "would",
    "why",
}
_EVIDENCE_TEXT_FIELDS = (
    "text",
    "doc_title",
    "summary",
    "section_title",
    "table_title",
    "table_caption",
    "table_row_label",
    "structured_search_text",
    "generated_doc_type",
    "doc_type",
)
_EVIDENCE_LIST_FIELDS = (
    "section_path",
    "topics",
    "table_column_headers",
    "structured_field_names",
)


@dataclass(frozen=True)
class EvidenceQuality:
    quality: str
    reasons: tuple[str, ...]
    max_retrieval_score: float
    max_rerank_score: float | None
    query_token_coverage: float
    distinct_doc_count: int

    @property
    def is_weak(self) -> bool:
        return self.quality == "weak"


def assess_evidence_quality(query: str, hits: list[SearchHit]) -> EvidenceQuality:
    if not hits:
        return EvidenceQuality(
            quality="weak",
            reasons=("no_hits",),
            max_retrieval_score=0.0,
            max_rerank_score=None,
            query_token_coverage=0.0,
            distinct_doc_count=0,
        )

    max_retrieval_score = max(hit.score for hit in hits)
    rerank_scores = [
        float(score)
        for hit in hits
        if (score := hit.payload.get("_rerank_score")) is not None and isinstance(score, int | float)
    ]
    query_tokens = _query_tokens(query)
    evidence_tokens = set().union(*(_hit_tokens(hit) for hit in hits[:3]))
    coverage = len(query_tokens & evidence_tokens) / len(query_tokens) if query_tokens else 0.0
    distinct_docs = {
        str(hit.payload["doc_id"])
        for hit in hits
        if hit.payload.get("doc_id") not in (None, "")
    }

    reasons: list[str] = []
    if max_retrieval_score >= STRONG_RETRIEVAL_SCORE:
        reasons.append("strong_retrieval_score")
    if coverage >= SUPPORTED_TOKEN_COVERAGE:
        reasons.append("strong_query_token_coverage")
    elif coverage >= PARTIAL_TOKEN_COVERAGE:
        reasons.append("partial_query_token_coverage")
    else:
        reasons.append("low_query_token_coverage")

    supported = (
        max_retrieval_score >= STRONG_RETRIEVAL_SCORE
        or coverage >= SUPPORTED_TOKEN_COVERAGE
        or (max_retrieval_score >= 0.3 and coverage >= PARTIAL_TOKEN_COVERAGE)
    )
    return EvidenceQuality(
        quality="supported" if supported else "weak",
        reasons=tuple(reasons),
        max_retrieval_score=max_retrieval_score,
        max_rerank_score=max(rerank_scores) if rerank_scores else None,
        query_token_coverage=coverage,
        distinct_doc_count=len(distinct_docs),
    )


def _query_tokens(query: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(query)
        if len(token) > 2 and token not in _QUERY_STOPWORDS
    }


def _hit_tokens(hit: SearchHit) -> set[str]:
    payload = hit.payload
    parts: list[str] = []
    for field in _EVIDENCE_TEXT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str):
            parts.append(value)
    for field in _EVIDENCE_LIST_FIELDS:
        value = payload.get(field)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    structured_fields = payload.get("structured_fields")
    if isinstance(structured_fields, list):
        for field in structured_fields:
            if isinstance(field, dict):
                parts.extend(str(value) for value in field.values())
    return normalized_match_tokens(" ".join(parts))
