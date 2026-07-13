"""Search, filtering, language, and route-specific retrieval policy."""

from __future__ import annotations

from ..core.config import Settings
from .cancellation import call_with_optional_cancellation
from .qdrant import QdrantClient, SearchHit
from .retrieval_hits import _optional_int
from .retrieval_structured import (
    _artifact_requires_structured_rows,
    _has_structured_evidence,
    _has_table_evidence,
    _has_table_row_lookup_signal,
)
from .routing_models import RoutePlan
from .sources import dedupe_hits
from .sparse import embed_sparse_text
from .temporal import target_date_for_query


def apply_route_retrieval_policy(
    hits: list[SearchHit], plan: RoutePlan | None
) -> list[SearchHit]:
    if plan is None or not hits:
        return hits
    ordered = hits
    if plan.use_structured_query or plan.search_mode == "structured_first":
        ordered = _promote_hits(ordered, _has_table_evidence)
    if plan.use_conflict_checker:
        ordered = _promote_hits(ordered, _has_claim_evidence)
    if (
        plan.retrieval_strategy == "source_metadata_lookup"
        or plan.search_mode == "metadata"
    ):
        ordered = _promote_hits(ordered, _has_source_metadata)
    if plan.retrieval_strategy in {
        "hybrid_parent_section_ordered",
        "symptom_cause_fix_hybrid",
    }:
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
    if (
        plan.retrieval_strategy == "source_metadata_lookup"
        or plan.search_mode == "metadata"
    ):
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


def add_document_scope(
    qdrant_filter: dict[str, object], document_ids: list[str]
) -> dict[str, object]:
    scoped_document_ids = sorted(
        {doc_id.strip() for doc_id in document_ids if doc_id.strip()}
    )
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


def prioritize_language(hits: list[SearchHit], language: str) -> list[SearchHit]:
    if language == "unknown":
        return hits
    return sorted(
        hits,
        key=lambda hit: (
            str(hit.payload.get("language", "unknown")) != language,
            -hit.score,
        ),
    )


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
        for field in (
            "page",
            "page_start",
            "page_end",
            "section_path",
            "parent_section_id",
        )
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
