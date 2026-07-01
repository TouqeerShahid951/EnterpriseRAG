"""ABAC-constrained retrieval for query graph nodes."""

from __future__ import annotations

import re

from rag.shared.contracts.structured_payloads import normalized_match_tokens, normalized_phrase

from ..auth.abac import build_abac_filter
from ..core.config import Settings
from .cancellation import call_with_optional_cancellation, cancellation_token_from_context
from .inference import InferenceClient
from .metadata_scoring import metadata_boost_hits
from .qdrant import QdrantClient, SearchHit
from .state import QueryContext, scoped_user_context
from .routing_models import RoutePlan
from .sparse import embed_sparse_text
from .sources import dedupe_hits
from .temporal import add_effective_date_scope, target_date_for_query

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
_DOCUMENT_SCOPE_SCAN_LIMIT = 5000
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
_BROAD_DOCUMENT_SCOPE_TOKENS = {"doc", "docs", "document", "documents", "file", "files", "source", "sources"}
_DOCUMENT_SCOPE_FOCUS_STOPWORDS = _DOCUMENT_SCOPE_STOPWORDS | _BROAD_DOCUMENT_SCOPE_TOKENS | {
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


def retrieve_candidates(
    ctx: QueryContext,
    *,
    config: Settings,
    ollama: InferenceClient,
    qdrant: QdrantClient,
) -> list[SearchHit]:
    hits: list[SearchHit] = []
    cancellation_token = cancellation_token_from_context(ctx)
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    plan = ctx.get("route_plan")
    artifact_plan = ctx.get("artifact_plan")
    active_query = ctx["query_rewritten"][-1] if ctx["query_rewritten"] else (plan.resolved_query if plan else ctx["request"].query)
    top_k = plan.top_k if plan else config.rag_top_k
    search_limit = top_k * _search_limit_multiplier(plan, active_query)
    if _artifact_requires_structured_rows(artifact_plan):
        search_limit = max(search_limit, top_k * 16)
    qdrant_filter = add_effective_date_scope(
        build_abac_filter(scoped_user_context(ctx), is_current_only=ctx["is_current_only"]),
        _target_date_from_plan(plan, active_query) if not ctx["is_current_only"] else None,
    )
    qdrant_filter = add_expiry_scope(qdrant_filter)
    if not getattr(config, "connector_include_stale_in_retrieval", False):
        qdrant_filter = add_stale_scope(qdrant_filter)
    qdrant_filter = add_document_scope(qdrant_filter, ctx["request"].document_ids)
    for query in ctx["sub_queries"] or [active_query]:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        dense_vector = call_with_optional_cancellation(ollama.embed, cancellation_token, query)
        if not call_with_optional_cancellation(qdrant.prepare_for_query, cancellation_token, len(dense_vector)):
            continue
        hits.extend(
            _search_query(
                query,
                dense_vector=dense_vector,
                limit=search_limit,
                qdrant_filter=qdrant_filter,
                config=config,
                qdrant=qdrant,
                cancellation_token=cancellation_token,
            )
        )
    ranked = prioritize_language(dedupe_hits(hits), query_language(active_query))
    ranked = metadata_boost_hits(active_query, ranked)
    ranked = apply_route_retrieval_policy(ranked, plan)
    ranked = _annotate_structured_hits(ranked, origin="direct")
    if _artifact_requires_structured_rows(artifact_plan) or _should_use_structured_path(active_query, ranked, plan):
        ranked = _promote_structured_matches(ranked, active_query)
        ranked = expand_structured_table_rows(
            ranked,
            qdrant=qdrant,
            qdrant_filter=qdrant_filter,
            cancellation_token=cancellation_token,
        )
    if _should_expand_document_scope(active_query, plan) and hasattr(qdrant, "retrieve_authorized_chunks"):
        scope_hits = call_with_optional_cancellation(
            qdrant.retrieve_authorized_chunks,
            cancellation_token,
            qdrant_filter=qdrant_filter,
            structured_only=False,
            limit=_DOCUMENT_SCOPE_SCAN_LIMIT,
        )
        document_scope_hits = _document_scope_hits(active_query, scope_hits)
        if document_scope_hits:
            scoped_doc_ids = _doc_ids(document_scope_hits)
            ranked = dedupe_hits([*document_scope_hits, *[hit for hit in ranked if _hit_doc_id(hit) in scoped_doc_ids]])
    if (
        _artifact_requires_structured_rows(artifact_plan)
        and ctx["request"].document_ids
        and hasattr(qdrant, "retrieve_document_chunks")
    ):
        scoped_chunks = call_with_optional_cancellation(
            qdrant.retrieve_document_chunks,
            cancellation_token,
            document_ids=ctx["request"].document_ids,
            qdrant_filter=qdrant_filter,
            structured_only=True,
            limit=2000,
        )
        ranked = dedupe_hits([*ranked, *_annotate_structured_hits(scoped_chunks, origin="scope_scan")])
    return apply_route_retrieval_policy(ranked, plan)


def apply_route_retrieval_policy(hits: list[SearchHit], plan: RoutePlan | None) -> list[SearchHit]:
    if plan is None or not hits:
        return hits
    ordered = hits
    if plan.use_structured_query or plan.search_mode == "structured_first":
        ordered = _promote_hits(ordered, _has_table_evidence)
    if plan.use_conflict_checker:
        ordered = _promote_hits(ordered, _has_claim_evidence)
    if plan.retrieval_strategy == "source_metadata_lookup" or plan.search_mode == "metadata":
        ordered = _promote_hits(ordered, _has_source_metadata)
    if plan.retrieval_strategy in {"hybrid_parent_section_ordered", "symptom_cause_fix_hybrid"}:
        ordered = _order_by_parent_section(ordered)
    return ordered


def merge_route_protected_hits(
    *,
    original_hits: list[SearchHit],
    ranked_hits: list[SearchHit],
    plan: RoutePlan | None,
) -> list[SearchHit]:
    if plan is None:
        return ranked_hits
    protected = route_protected_hits(original_hits, plan)
    return apply_route_retrieval_policy(dedupe_hits([*ranked_hits, *protected]), plan)


def merge_artifact_protected_hits(
    *,
    original_hits: list[SearchHit],
    ranked_hits: list[SearchHit],
    artifact_plan: object | None,
) -> list[SearchHit]:
    if not _artifact_requires_structured_rows(artifact_plan):
        return ranked_hits
    structured = [hit for hit in original_hits if _has_structured_evidence(hit)]
    return dedupe_hits([*ranked_hits, *structured])


def route_protected_hits(hits: list[SearchHit], plan: RoutePlan) -> list[SearchHit]:
    if plan.use_structured_query or plan.search_mode == "structured_first":
        return [hit for hit in hits if _has_table_evidence(hit)]
    if plan.use_conflict_checker:
        return [hit for hit in hits if _has_claim_evidence(hit)]
    if plan.retrieval_strategy == "source_metadata_lookup" or plan.search_mode == "metadata":
        return [hit for hit in hits if _has_source_metadata(hit)]
    return []


def _target_date_from_plan(plan: object, query: str) -> str | None:
    if plan is not None:
        filters = getattr(plan, "filters", {})
        if isinstance(filters, dict) and isinstance(filters.get("target_date"), str):
            return filters["target_date"]
    return target_date_for_query(query)


def _search_limit_multiplier(plan: RoutePlan | None, query: str = "") -> int:
    multiplier = _base_search_limit_multiplier(plan)
    if _has_table_row_lookup_signal(query):
        multiplier = max(multiplier, 16)
    return multiplier


def _base_search_limit_multiplier(plan: RoutePlan | None) -> int:
    if plan is None:
        return 4
    if plan.use_structured_query or plan.search_mode == "structured_first":
        return 8
    if plan.use_conflict_checker or plan.search_mode == "metadata":
        return 6
    return 4


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
        for signal in ("highest", "lowest", "maximum", "minimum", "max", "min", "largest", "smallest", "most", "least")
    )


def _should_expand_structured_rows(query: str) -> bool:
    return _has_table_superlative_signal(query) or _has_table_row_lookup_signal(query)


def _should_use_structured_path(query: str, hits: list[SearchHit], plan: RoutePlan | None) -> bool:
    if not hits:
        return False
    if plan is not None and plan.use_structured_query and _should_expand_structured_rows(query):
        return True
    structured_hits = [hit for hit in hits if _has_structured_evidence(hit)]
    if not structured_hits:
        return False
    if _should_expand_structured_rows(query):
        return True
    return any(_structured_field_match_score(query, hit) > 0 for hit in structured_hits[:12])


def _artifact_requires_structured_rows(artifact_plan: object | None) -> bool:
    return getattr(artifact_plan, "primary_operation", None) in {"enumerate", "extract"}


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
        matched = _documents_matching_scope_tokens(tokens - _BROAD_DOCUMENT_SCOPE_TOKENS or tokens, metadata_by_doc)
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
    return any(tokens and tokens <= _BROAD_DOCUMENT_SCOPE_TOKENS for tokens in _document_scope_token_groups(query))


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


def _hit_focus_tokens(hit: SearchHit) -> set[str]:
    payload = hit.payload
    tokens: set[str] = set()
    for field in (
        "doc_title",
        "doc_summary",
        "doc_type",
        "generated_doc_type",
        "auto_doc_type",
        "section_title",
        "table_title",
        "table_caption",
        "table_row_label",
        "text",
        "parent_text",
        "structured_search_text",
    ):
        value = payload.get(field)
        if isinstance(value, str):
            tokens.update(normalized_match_tokens(value))
    for field in ("topics", "llm_topics", "metadata_terms", "section_path", "table_column_headers"):
        value = payload.get(field)
        if isinstance(value, list):
            tokens.update(token for item in value for token in normalized_match_tokens(item))
    return tokens


def _scope_tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(text)
        if len(token) > 2 and token not in _DOCUMENT_SCOPE_STOPWORDS
    }


def _documents_matching_scope_tokens(tokens: set[str], metadata_by_doc: dict[str, set[str]]) -> set[str]:
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
            tokens.update(token for item in value for token in normalized_match_tokens(item))
    return tokens


def _doc_ids(hits: list[SearchHit]) -> set[str]:
    return {_hit_doc_id(hit) for hit in hits}


def _hit_doc_id(hit: SearchHit) -> str:
    return str(hit.payload.get("doc_id", hit.point_id))


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
        _optional_int(payload.get("page_start")) or _optional_int(payload.get("page")) or 10**9,
        _optional_int(payload.get("table_row_index")) or 0,
        str(payload.get("chunk_id", hit.point_id)),
    )


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
        str(hit.payload.get("chunk_id", hit.point_id))
        for hit in hits
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
                    if str(row.payload.get("chunk_id", row.point_id)) not in original_chunk_ids
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
    if payload.get("chunk_type") != "table_row" and payload.get("structured_kind") != "table_row" and not (isinstance(table_json, dict) and table_json):
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


def add_document_scope(qdrant_filter: dict[str, object], document_ids: list[str]) -> dict[str, object]:
    scoped_document_ids = sorted({doc_id.strip() for doc_id in document_ids if doc_id.strip()})
    if not scoped_document_ids:
        return qdrant_filter

    scoped = dict(qdrant_filter)
    must = list(scoped.get("must", []))
    must.append(
        {
            "should": [
                {"key": "doc_id", "match": {"value": doc_id}}
                for doc_id in scoped_document_ids
            ]
        }
    )
    scoped["must"] = must
    return scoped


def add_expiry_scope(qdrant_filter: dict[str, object]) -> dict[str, object]:
    scoped = dict(qdrant_filter)
    must = list(scoped.get("must", []))
    must.append(not_expired_condition())
    scoped["must"] = must
    return scoped


def add_stale_scope(qdrant_filter: dict[str, object]) -> dict[str, object]:
    scoped = dict(qdrant_filter)
    must = list(scoped.get("must", []))
    must.append(not_stale_condition())
    scoped["must"] = must
    return scoped


def not_expired_condition() -> dict[str, object]:
    return {
        "should": [
            {"key": "is_expired", "match": {"value": False}},
            {"is_empty": {"key": "is_expired"}},
        ]
    }


def not_stale_condition() -> dict[str, object]:
    return {
        "must": [
            {
                "should": [
                    {"key": "source_deleted", "match": {"value": False}},
                    {"is_empty": {"key": "source_deleted"}},
                ]
            },
            {
                "should": [
                    {"key": "retrieval_status", "match": {"value": "active"}},
                    {"is_empty": {"key": "retrieval_status"}},
                ]
            },
        ]
    }


def topics_for_query(query: str) -> list[str]:
    return []


def prioritize_language(hits: list[SearchHit], language: str) -> list[SearchHit]:
    if language == "unknown":
        return hits
    return sorted(hits, key=lambda hit: (str(hit.payload.get("language", "unknown")) != language, -hit.score))


def query_language(query: str) -> str:
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(query)
    except Exception:
        return "unknown"


def _promote_hits(hits: list[SearchHit], predicate) -> list[SearchHit]:
    promoted: list[SearchHit] = []
    remaining: list[SearchHit] = []
    for hit in hits:
        (promoted if predicate(hit) else remaining).append(hit)
    return promoted + remaining


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
    return isinstance(field_names, list) and any(isinstance(name, str) and name.strip() for name in field_names)


def _has_claim_evidence(hit: SearchHit) -> bool:
    claims = hit.payload.get("claims")
    claim_ids = hit.payload.get("claim_ids")
    return (
        bool(hit.payload.get("has_conflict"))
        or (isinstance(claims, list) and bool(claims))
        or (isinstance(claim_ids, list) and bool(claim_ids))
    )


def _has_source_metadata(hit: SearchHit) -> bool:
    payload = hit.payload
    return any(
        payload.get(field) not in (None, "", [])
        for field in ("page", "page_start", "page_end", "section_path", "parent_section_id")
    )


def _order_by_parent_section(hits: list[SearchHit]) -> list[SearchHit]:
    return sorted(hits, key=_parent_section_sort_key)


def _parent_section_sort_key(hit: SearchHit) -> tuple[str, str, int, str]:
    payload = hit.payload
    doc_id = str(payload.get("doc_id", hit.point_id))
    parent = _parent_key(payload)
    page = (
        _optional_int(payload.get("parent_page_start"))
        or _optional_int(payload.get("page_start"))
        or _optional_int(payload.get("page"))
        or 10**9
    )
    chunk_id = str(payload.get("chunk_id", hit.point_id))
    return (doc_id, parent, page, chunk_id)


def _parent_key(payload: dict[str, object]) -> str:
    for field in ("parent_section_id", "parent_chunk_id", "chunk_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    section_path = payload.get("section_path")
    if isinstance(section_path, list):
        return " / ".join(str(part) for part in section_path if str(part).strip())
    return ""


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _annotate_structured_hits(hits: list[SearchHit], *, origin: str) -> list[SearchHit]:
    annotated: list[SearchHit] = []
    for hit in hits:
        if not _has_structured_evidence(hit):
            annotated.append(hit)
            continue
        payload = dict(hit.payload)
        payload["structured_origin"] = payload.get("structured_origin") or origin
        annotated.append(SearchHit(point_id=hit.point_id, score=hit.score, payload=payload))
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
        label_tokens = {token for token in normalized_match_tokens(raw_name) if len(token) > 2}
        overlap = query_tokens & label_tokens
        if not overlap:
            continue
        score = len(overlap)
        label_phrase = normalized_phrase(raw_name)
        if label_phrase and label_phrase in query_phrase:
            score += 2
        best_score = max(best_score, score)
    return best_score


def _search_query(
    query: str,
    *,
    dense_vector: list[float],
    limit: int,
    qdrant_filter: dict[str, object],
    config: Settings,
    qdrant: QdrantClient,
    cancellation_token=None,
) -> list[SearchHit]:
    if not hasattr(qdrant, "hybrid_search"):
        return call_with_optional_cancellation(
            qdrant.search,
            cancellation_token,
            dense_vector,
            limit=limit,
            qdrant_filter=qdrant_filter,
        )
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    sparse_vector = embed_sparse_text(
        query,
        model_name=config.rag_sparse_model,
        cache_dir=config.rag_sparse_cache_dir,
    )
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    return call_with_optional_cancellation(
        qdrant.hybrid_search,
        cancellation_token,
        dense_vector=dense_vector,
        sparse_vector=sparse_vector.as_qdrant(),
        limit=limit,
        qdrant_filter=qdrant_filter,
    )
