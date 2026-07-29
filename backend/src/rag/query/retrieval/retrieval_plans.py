"""Compile typed retrieval capabilities into executable settings."""

from __future__ import annotations

from typing import get_args

from rag.query.retrieval.temporal import target_date_for_query
from rag.query.routing.routing_models import (
    CoverageMode,
    QueryScope,
    ResponseMode,
    RetrievalCapability,
    RiskLevel,
    TemporalScope,
)


def retrieval_settings_for(
    capabilities: tuple[RetrievalCapability, ...],
    *,
    response_mode: ResponseMode,
    scope: QueryScope,
    coverage: CoverageMode,
    temporal_scope: TemporalScope,
    query: str,
    base_top_k: int,
) -> dict[str, object]:
    """Return server-owned execution settings for a validated capability plan."""
    selected = set(capabilities) or {"general_search"}
    unknown = selected.difference(get_args(RetrievalCapability))
    if unknown:
        raise ValueError(
            f"Unsupported retrieval capabilities: {', '.join(sorted(unknown))}"
        )

    top_k = max(1, base_top_k)
    chunk_granularity = "medium"
    if coverage == "exhaustive":
        chunk_granularity = "document"
        top_k = max(top_k, 24)
    elif "document_search" in selected:
        chunk_granularity = "document" if scope == "corpus" else "section"
        top_k = max(top_k, 8)
    elif selected & {"structured_query", "document_navigation"}:
        chunk_granularity = "section"

    if "structured_query" in selected:
        top_k = max(top_k, 24)
    elif "global_graph" in selected:
        top_k = max(top_k, 8)
    elif selected & {"document_navigation", "decomposed_search"}:
        top_k = max(top_k, 6)
    if response_mode == "conflict_analysis":
        top_k = max(top_k, 8)

    target_date = target_date_for_query(query)
    filters: dict[str, object] = {}
    if target_date is not None:
        filters["target_date"] = target_date

    return {
        "needs_retrieval": True,
        "retrieval_strategy": _compatibility_strategy(selected, response_mode),
        "search_mode": (
            "structured_first"
            if "structured_query" in selected
            else "metadata"
            if "document_navigation" in selected
            else "multi_query_hybrid"
            if "decomposed_search" in selected
            else "hybrid"
        ),
        "use_query_planner": "decomposed_search" in selected,
        "use_reranker": True,
        "use_temporal_filter": temporal_scope in {"historical", "as_of"}
        or target_date is not None,
        "use_conflict_checker": response_mode == "conflict_analysis",
        "use_structured_query": "structured_query" in selected,
        "chunk_granularity": chunk_granularity,
        "top_k": top_k,
        "filters": filters,
        "allow_abstain": True,
        "risk_level": _risk_level(
            selected,
            response_mode=response_mode,
            coverage=coverage,
            temporal_scope=temporal_scope,
        ),
    }


def _compatibility_strategy(capabilities: set[str], response_mode: ResponseMode) -> str:
    """Keep old executors working while capabilities become authoritative."""
    if "global_graph" in capabilities:
        return "graphrag_global"
    if "live_sql" in capabilities:
        return "live_sql_hybrid"
    if "structured_query" in capabilities:
        return "structured_table_metadata_first"
    if "document_navigation" in capabilities:
        return "source_metadata_lookup"
    if "document_search" in capabilities:
        return "section_or_document_summary"
    if "decomposed_search" in capabilities:
        return "planned_subquery_hybrid"
    if response_mode == "conflict_analysis":
        return "competing_claims_hybrid"
    return "hybrid_reranked"


def _risk_level(
    capabilities: set[str],
    *,
    response_mode: ResponseMode,
    coverage: CoverageMode,
    temporal_scope: TemporalScope,
) -> RiskLevel:
    if (
        coverage == "exhaustive"
        or response_mode == "conflict_analysis"
        or capabilities & {"structured_query", "live_sql", "global_graph"}
    ):
        return "high"
    if temporal_scope in {"historical", "as_of"} or capabilities & {
        "document_search",
        "document_navigation",
        "decomposed_search",
    }:
        return "medium"
    return "low"
