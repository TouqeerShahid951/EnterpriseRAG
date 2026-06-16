"""Soft metadata scoring for retrieval and reranking."""

from __future__ import annotations

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from .qdrant import SearchHit

_STOPWORDS = {
    "and",
    "document",
    "documents",
    "from",
    "give",
    "list",
    "manual",
    "policy",
    "procedure",
    "report",
    "show",
    "the",
    "what",
    "which",
    "with",
}
_TEXT_FIELDS = (
    "doc_title",
    "doc_summary",
    "doc_type",
    "generated_doc_type",
    "auto_doc_type",
    "section_title",
    "table_title",
    "table_caption",
    "table_row_label",
)
_LIST_FIELDS = (
    "topics",
    "llm_topics",
    "metadata_terms",
    "section_path",
    "table_column_headers",
    "structured_field_names",
)


def annotate_metadata_matches(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    query_tokens = _query_tokens(query)
    if not query_tokens:
        return hits
    annotated: list[SearchHit] = []
    for hit in hits:
        matches = sorted(query_tokens & _metadata_tokens(hit))
        score = min(1.0, len(matches) / max(2, len(query_tokens))) if matches else 0.0
        if score <= 0:
            annotated.append(hit)
            continue
        annotated.append(
            SearchHit(
                point_id=hit.point_id,
                score=hit.score,
                payload={
                    **hit.payload,
                    "_metadata_score": round(score, 3),
                    "_metadata_matches": matches[:12],
                    "_metadata_boosted_score": round(hit.score + min(0.15, score * 0.15), 6),
                },
            )
        )
    return annotated


def metadata_boost_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    annotated = annotate_metadata_matches(query, hits)
    ordered = sorted(
        enumerate(annotated),
        key=lambda item: (
            -float(item[1].payload.get("_metadata_boosted_score", item[1].score)),
            -float(item[1].payload.get("_metadata_score", 0.0)),
            item[0],
        ),
    )
    return [hit for _, hit in ordered]


def metadata_score(hit: SearchHit) -> float:
    value = hit.payload.get("_metadata_score", 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def _metadata_tokens(hit: SearchHit) -> set[str]:
    payload = hit.payload
    tokens: set[str] = set()
    for field in _TEXT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str):
            tokens.update(normalized_match_tokens(value))
    for field in _LIST_FIELDS:
        value = payload.get(field)
        if isinstance(value, list):
            for item in value:
                tokens.update(normalized_match_tokens(str(item)))
    return {token for token in tokens if len(token) > 2}


def _query_tokens(query: str) -> set[str]:
    return {token for token in normalized_match_tokens(query) if len(token) > 2 and token not in _STOPWORDS}
