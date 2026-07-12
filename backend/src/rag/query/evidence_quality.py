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
    "all",
    "can",
    "citation",
    "citations",
    "compare",
    "could",
    "describe",
    "does",
    "doing",
    "each",
    "document",
    "documents",
    "evidence",
    "every",
    "explain",
    "find",
    "for",
    "from",
    "give",
    "has",
    "have",
    "how",
    "in",
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
    "table_column_headers",
    "structured_field_names",
)
_DOCUMENT_CLASS_FIELDS = (
    "doc_title",
    "doc_type",
    "generated_doc_type",
    "auto_doc_type",
    "source_id",
)
_AGGREGATION_INTENTS = {"aggregation"}
_SUMMARY_INTENTS = {"summarization", "comparative_summary", "general_rag", "graphrag_global"}
_COMPARISON_INTENTS = {"comparison", "temporal_comparison", "comparative_summary"}
_NAVIGATION_INTENTS = {"document_navigation"}


@dataclass(frozen=True)
class EvidenceQuality:
    quality: str
    reasons: tuple[str, ...]
    max_retrieval_score: float
    max_rerank_score: float | None
    query_token_coverage: float
    distinct_doc_count: int
    evidence_score: float = 0.0
    outcome: str = "degrade"
    structured_hit_count: int = 0
    metadata_hit_count: int = 0
    document_class_match_count: int = 0
    exhaustive_scope_match_count: int = 0
    in_scope_doc_ids: frozenset[str] = frozenset()

    @property
    def is_weak(self) -> bool:
        return self.quality == "weak"


def assess_evidence_quality(query: str, hits: list[SearchHit], *, route_plan: object | None = None) -> EvidenceQuality:
    if not hits:
        return EvidenceQuality(
            quality="weak",
            reasons=("no_hits",),
            max_retrieval_score=0.0,
            max_rerank_score=None,
            query_token_coverage=0.0,
            distinct_doc_count=0,
            outcome="degrade",
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
    structured_hit_count = sum(1 for hit in hits if _is_structured_hit(hit))
    metadata_hit_count = sum(1 for hit in hits if _has_source_metadata(hit))
    in_scope_doc_ids = _document_class_doc_ids(query_tokens, hits)
    exhaustive_scope_doc_ids = _exhaustive_scope_doc_ids(query_tokens, hits)
    document_class_match_count = len(in_scope_doc_ids)
    exhaustive_scope_match_count = len(exhaustive_scope_doc_ids)

    reasons: list[str] = []
    if max_retrieval_score >= STRONG_RETRIEVAL_SCORE:
        reasons.append("strong_retrieval_score")
    if coverage >= SUPPORTED_TOKEN_COVERAGE:
        reasons.append("strong_query_token_coverage")
    elif coverage >= PARTIAL_TOKEN_COVERAGE:
        reasons.append("partial_query_token_coverage")
    else:
        reasons.append("low_query_token_coverage")

    route_intent = str(getattr(route_plan, "intent", "") or "")
    score = _combined_evidence_score(
        route_intent=route_intent,
        max_retrieval_score=max_retrieval_score,
        max_rerank_score=max(rerank_scores) if rerank_scores else None,
        query_token_coverage=coverage,
        distinct_doc_count=len(distinct_docs),
        structured_hit_count=structured_hit_count,
        metadata_hit_count=metadata_hit_count,
        document_class_match_count=document_class_match_count,
        exhaustive_scope_match_count=exhaustive_scope_match_count,
    )
    outcome = _evidence_outcome(
        route_intent=route_intent,
        score=score,
        max_retrieval_score=max_retrieval_score,
        query_token_coverage=coverage,
        distinct_doc_count=len(distinct_docs),
        structured_hit_count=structured_hit_count,
        metadata_hit_count=metadata_hit_count,
        document_class_match_count=document_class_match_count,
        exhaustive_scope_match_count=exhaustive_scope_match_count,
    )
    reasons.extend(_score_reasons(
        route_intent,
        score,
        outcome,
        structured_hit_count,
        metadata_hit_count,
        document_class_match_count,
        exhaustive_scope_match_count,
    ))
    quality = "supported" if outcome == "pass" else "partial" if outcome == "partial" else "weak"
    return EvidenceQuality(
        quality=quality,
        reasons=tuple(reasons),
        max_retrieval_score=max_retrieval_score,
        max_rerank_score=max(rerank_scores) if rerank_scores else None,
        query_token_coverage=coverage,
        distinct_doc_count=len(distinct_docs),
        evidence_score=score,
        outcome=outcome,
        structured_hit_count=structured_hit_count,
        metadata_hit_count=metadata_hit_count,
        document_class_match_count=document_class_match_count,
        exhaustive_scope_match_count=exhaustive_scope_match_count,
        in_scope_doc_ids=frozenset(in_scope_doc_ids | exhaustive_scope_doc_ids),
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


def _combined_evidence_score(
    *,
    route_intent: str,
    max_retrieval_score: float,
    max_rerank_score: float | None,
    query_token_coverage: float,
    distinct_doc_count: int,
    structured_hit_count: int,
    metadata_hit_count: int,
    document_class_match_count: int,
    exhaustive_scope_match_count: int,
) -> float:
    features = {
        "retrieval": _clamp(max_retrieval_score / STRONG_RETRIEVAL_SCORE),
        "rerank": _rerank_confidence(max_rerank_score),
        "lexical": _clamp(query_token_coverage),
        "breadth": _clamp(distinct_doc_count / 4),
        "structured": _clamp(structured_hit_count / 6),
        "metadata": _clamp(metadata_hit_count / 6),
        "doc_class": _clamp((document_class_match_count + exhaustive_scope_match_count) / 3),
    }
    weights = _route_weights(route_intent)
    return round(sum(features[name] * weight for name, weight in weights.items()), 3)


def _evidence_outcome(
    *,
    route_intent: str,
    score: float,
    max_retrieval_score: float,
    query_token_coverage: float,
    distinct_doc_count: int,
    structured_hit_count: int,
    metadata_hit_count: int,
    document_class_match_count: int,
    exhaustive_scope_match_count: int,
) -> str:
    if route_intent in _AGGREGATION_INTENTS:
        if exhaustive_scope_match_count > 0 and query_token_coverage >= SUPPORTED_TOKEN_COVERAGE:
            return "pass"
        if exhaustive_scope_match_count > 0 and query_token_coverage >= PARTIAL_TOKEN_COVERAGE:
            return "partial"
        has_aggregate_support = (
            document_class_match_count > 0
            or structured_hit_count > 0
            or distinct_doc_count >= 2
        )
        if has_aggregate_support and score >= 0.50:
            return "pass"
        if has_aggregate_support and score >= 0.35:
            return "partial"
        return "degrade"
    if route_intent in _NAVIGATION_INTENTS:
        if metadata_hit_count > 0 and score >= 0.45:
            return "pass"
        return "partial" if metadata_hit_count > 0 else "degrade"
    if route_intent in _COMPARISON_INTENTS and distinct_doc_count >= 2 and score >= 0.50:
        return "pass"
    if route_intent in _SUMMARY_INTENTS and distinct_doc_count >= 1 and score >= 0.50:
        return "pass"
    if (
        max_retrieval_score >= STRONG_RETRIEVAL_SCORE
        or query_token_coverage >= SUPPORTED_TOKEN_COVERAGE
        or (max_retrieval_score >= 0.3 and query_token_coverage >= PARTIAL_TOKEN_COVERAGE)
        or (score >= 0.58 and query_token_coverage >= PARTIAL_TOKEN_COVERAGE)
    ):
        return "pass"
    if score >= 0.45 and (max_retrieval_score >= 0.3 or query_token_coverage >= PARTIAL_TOKEN_COVERAGE):
        return "partial"
    return "degrade"


def _route_weights(route_intent: str) -> dict[str, float]:
    if route_intent in _AGGREGATION_INTENTS:
        return {
            "retrieval": 0.10,
            "rerank": 0.05,
            "lexical": 0.10,
            "breadth": 0.25,
            "structured": 0.20,
            "metadata": 0.10,
            "doc_class": 0.20,
        }
    if route_intent in _NAVIGATION_INTENTS:
        return {
            "retrieval": 0.15,
            "rerank": 0.05,
            "lexical": 0.15,
            "breadth": 0.05,
            "structured": 0.05,
            "metadata": 0.45,
            "doc_class": 0.10,
        }
    if route_intent in _COMPARISON_INTENTS:
        return {
            "retrieval": 0.15,
            "rerank": 0.10,
            "lexical": 0.25,
            "breadth": 0.25,
            "structured": 0.10,
            "metadata": 0.05,
            "doc_class": 0.10,
        }
    if route_intent in _SUMMARY_INTENTS:
        return {
            "retrieval": 0.20,
            "rerank": 0.05,
            "lexical": 0.20,
            "breadth": 0.20,
            "structured": 0.10,
            "metadata": 0.15,
            "doc_class": 0.10,
        }
    return {
        "retrieval": 0.35,
        "rerank": 0.10,
        "lexical": 0.35,
        "breadth": 0.05,
        "structured": 0.05,
        "metadata": 0.05,
        "doc_class": 0.05,
    }


def _score_reasons(
    route_intent: str,
    score: float,
    outcome: str,
    structured_hit_count: int,
    metadata_hit_count: int,
    document_class_match_count: int,
    exhaustive_scope_match_count: int,
) -> list[str]:
    reasons = [f"evidence_score_{score:.2f}", f"verifier_outcome_{outcome}"]
    if route_intent:
        reasons.append(f"route_policy_{route_intent}")
    if structured_hit_count:
        reasons.append("structured_evidence_present")
    if metadata_hit_count:
        reasons.append("source_metadata_present")
    if document_class_match_count:
        reasons.append("document_class_match")
    if exhaustive_scope_match_count:
        reasons.append("exhaustive_scope_match")
    return reasons


def _document_class_doc_ids(query_tokens: set[str], hits: list[SearchHit]) -> set[str]:
    if not query_tokens:
        return set()
    matched: set[str] = set()
    for hit in hits:
        doc_id = str(hit.payload.get("doc_id", hit.point_id))
        if query_tokens & _document_class_tokens(hit):
            matched.add(doc_id)
    return matched


def _exhaustive_scope_doc_ids(query_tokens: set[str], hits: list[SearchHit]) -> set[str]:
    if not query_tokens:
        return set()
    matched: set[str] = set()
    for hit in hits:
        if str(hit.payload.get("exhaustive_scope_origin", "")) != "document_class_scope":
            continue
        if query_tokens & _hit_tokens(hit):
            matched.add(str(hit.payload.get("doc_id", hit.point_id)))
    return matched


def _document_class_tokens(hit: SearchHit) -> set[str]:
    parts: list[str] = []
    for field in _DOCUMENT_CLASS_FIELDS:
        value = hit.payload.get(field)
        if isinstance(value, str):
            parts.append(value)
    return normalized_match_tokens(" ".join(parts))


def _is_structured_hit(hit: SearchHit) -> bool:
    payload = hit.payload
    if payload.get("chunk_type") in {"table", "table_row", "kv_record"}:
        return True
    structured_kind = payload.get("structured_kind")
    if isinstance(structured_kind, str) and structured_kind.strip():
        return True
    table_json = payload.get("table_json")
    structured_fields = payload.get("structured_fields")
    return isinstance(table_json, dict) and bool(table_json) or isinstance(structured_fields, list) and bool(structured_fields)


def _has_source_metadata(hit: SearchHit) -> bool:
    return any(
        hit.payload.get(field) not in (None, "", [])
        for field in ("page", "page_start", "page_end", "section_path", "parent_section_id")
    )


def _rerank_confidence(score: float | None) -> float:
    if score is None:
        return 0.0
    return _clamp((score + 1.0) / 2.0)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
