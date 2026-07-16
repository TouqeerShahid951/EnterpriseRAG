"""Structured-table retrieval expansion and ranking policy."""

from __future__ import annotations

from rag.shared.contracts.structured_payloads import (
    normalized_match_tokens,
    normalized_phrase,
)

from rag.query.cancellation import call_with_optional_cancellation
from rag.query.qdrant import QdrantClient, SearchHit
from rag.query.retrieval.retrieval_hits import _optional_int
from rag.query.routing.routing_models import RoutePlan
from rag.query.sources import dedupe_hits

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


def _has_table_row_lookup_signal(query: str) -> bool:
    normalized = query.lower()
    return any(
        signal in normalized
        for signal in (
            " number of ",
            " give me the list ",
            " give me the list of ",
            " option",
            " options",
            " available",
            " supported",
            " include",
            " includes",
            " listing",
            " listed",
            " list ",
            " list all ",
            " list the ",
            " show all ",
            " show me all ",
        )
    )


def _has_table_superlative_signal(query: str) -> bool:
    normalized = query.lower()
    return any(
        f" {signal} " in f" {normalized} "
        for signal in (
            "highest",
            "lowest",
            "maximum",
            "minimum",
            "max",
            "min",
            "largest",
            "smallest",
            "most",
            "least",
        )
    )


def _should_expand_structured_rows(query: str) -> bool:
    return _has_table_superlative_signal(query) or _has_table_row_lookup_signal(query)


def _should_use_structured_path(
    query: str, hits: list[SearchHit], plan: RoutePlan | None
) -> bool:
    if not hits:
        return False
    if (
        plan is not None
        and plan.use_structured_query
        and _should_expand_structured_rows(query)
    ):
        return True
    structured_hits = [hit for hit in hits if _has_structured_evidence(hit)]
    if not structured_hits:
        return False
    if _should_expand_structured_rows(query):
        return True
    return any(
        _structured_field_match_score(query, hit) > 0 for hit in structured_hits[:12]
    )


def _artifact_requires_structured_rows(artifact_plan: object | None) -> bool:
    return getattr(artifact_plan, "primary_operation", None) in {"enumerate", "extract"}


def expand_structured_table_rows(
    hits: list[SearchHit],
    *,
    qdrant: QdrantClient,
    qdrant_filter: dict[str, object],
    cancellation_token=None,
    limit_per_table: int = 64,
) -> list[SearchHit]:
    if not hits or not hasattr(qdrant, "retrieve_table_rows"):
        return hits
    expanded: list[SearchHit] = []
    original_chunk_ids = {
        str(hit.payload.get("chunk_id", hit.point_id)) for hit in hits
    }
    seen_tables: set[tuple[str, str]] = set()
    for hit in hits:
        key = _table_key(hit)
        if key is None or key in seen_tables:
            continue
        seen_tables.add(key)
        doc_id, table_title = key
        sibling_rows = call_with_optional_cancellation(
            qdrant.retrieve_table_rows,
            cancellation_token,
            doc_id=doc_id,
            table_title=table_title,
            qdrant_filter=qdrant_filter,
            limit=limit_per_table,
        )
        expanded.extend(
            _annotate_structured_hits(
                [
                    row
                    for row in _sort_table_rows(sibling_rows)
                    if str(row.payload.get("chunk_id", row.point_id))
                    not in original_chunk_ids
                ],
                origin="sibling",
            )
        )
    return dedupe_hits([*hits, *expanded])


def _table_key(hit: SearchHit) -> tuple[str, str] | None:
    payload = hit.payload
    doc_id = payload.get("doc_id")
    table_title = payload.get("table_title")
    if not isinstance(doc_id, str) or not doc_id.strip():
        return None
    if not isinstance(table_title, str) or not table_title.strip():
        return None
    table_json = payload.get("table_json")
    if (
        payload.get("chunk_type") != "table_row"
        and payload.get("structured_kind") != "table_row"
        and not (isinstance(table_json, dict) and table_json)
    ):
        return None
    return doc_id.strip(), table_title.strip()


def _sort_table_rows(hits: list[SearchHit]) -> list[SearchHit]:
    return sorted(
        hits,
        key=lambda hit: (
            _optional_int(hit.payload.get("table_row_index")) is None,
            _optional_int(hit.payload.get("table_row_index")) or 0,
            str(hit.payload.get("chunk_id", hit.point_id)),
        ),
    )


def _has_table_evidence(hit: SearchHit) -> bool:
    if _has_structured_evidence(hit):
        return True
    table_json = hit.payload.get("table_json")
    return isinstance(table_json, dict) and bool(table_json)


def _has_structured_evidence(hit: SearchHit) -> bool:
    structured_kind = hit.payload.get("structured_kind")
    if isinstance(structured_kind, str) and structured_kind.strip():
        return True
    if hit.payload.get("chunk_type") == "table_row":
        return True
    table_json = hit.payload.get("table_json")
    if isinstance(table_json, dict) and bool(table_json):
        return True
    field_names = hit.payload.get("structured_field_names")
    return isinstance(field_names, list) and any(
        isinstance(name, str) and name.strip() for name in field_names
    )


def _annotate_structured_hits(hits: list[SearchHit], *, origin: str) -> list[SearchHit]:
    annotated: list[SearchHit] = []
    for hit in hits:
        if not _has_structured_evidence(hit):
            annotated.append(hit)
            continue
        payload = dict(hit.payload)
        payload["structured_origin"] = payload.get("structured_origin") or origin
        annotated.append(
            SearchHit(point_id=hit.point_id, score=hit.score, payload=payload)
        )
    return annotated


def _promote_structured_matches(hits: list[SearchHit], query: str) -> list[SearchHit]:
    scored = [
        (
            hit,
            _structured_field_match_score(query, hit),
            0 if str(hit.payload.get("structured_origin", "")) == "direct" else 1,
        )
        for hit in hits
    ]
    return [
        hit
        for hit, _, _ in sorted(
            scored,
            key=lambda item: (-item[1], item[2], -item[0].score),
        )
    ]


def _structured_field_match_score(query: str, hit: SearchHit) -> int:
    field_names = hit.payload.get("structured_field_names")
    if not isinstance(field_names, list):
        return 0
    query_tokens = {
        token
        for token in normalized_match_tokens(query)
        if len(token) > 2 and token not in _STRUCTURED_QUERY_STOPWORDS
    }
    if not query_tokens:
        return 0
    query_phrase = normalized_phrase(query)
    best_score = 0
    for raw_name in field_names:
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        label_tokens = {
            token for token in normalized_match_tokens(raw_name) if len(token) > 2
        }
        overlap = query_tokens & label_tokens
        if not overlap:
            continue
        score = len(overlap)
        label_phrase = normalized_phrase(raw_name)
        if label_phrase and label_phrase in query_phrase:
            score += 2
        best_score = max(best_score, score)
    return best_score
