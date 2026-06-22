"""Retrieval settings derived from internal route intents."""

from __future__ import annotations

from .routing_models import RouteIntent, RiskLevel
from .temporal import target_date_for_query


def retrieval_settings_for(intent: RouteIntent, *, query: str, base_top_k: int) -> dict[str, object]:
    base_top_k = max(1, base_top_k)
    target_date = target_date_for_query(query)
    temporal_scope = _has_temporal_scope(query, target_date)
    settings = {
        "needs_retrieval": True,
        "retrieval_strategy": "hybrid_reranked",
        "search_mode": "hybrid",
        "use_query_planner": False,
        "use_reranker": True,
        "use_temporal_filter": False,
        "use_conflict_checker": False,
        "use_structured_query": False,
        "chunk_granularity": "medium",
        "top_k": base_top_k,
        "filters": {},
        "allow_abstain": True,
        "risk_level": _risk_level(intent),
    }
    if intent in {"procedural", "troubleshooting_procedure"}:
        settings.update(
            retrieval_strategy="hybrid_parent_section_ordered",
            chunk_granularity="section",
            top_k=max(base_top_k, 6),
        )
    elif intent == "summarization":
        if _is_section_scoped_summary(query):
            settings.update(
                retrieval_strategy="section_or_document_summary",
                chunk_granularity="section",
                top_k=max(base_top_k, 8),
            )
        else:
            settings.update(
                retrieval_strategy="section_or_document_summary",
                use_query_planner=True,
                use_reranker=False,
                chunk_granularity="document",
                top_k=max(base_top_k, 4),
            )
    elif intent in {"comparison", "temporal_comparison", "comparative_summary"}:
        settings.update(
            retrieval_strategy="multi_query_hybrid_balanced",
            search_mode="multi_query_hybrid",
            use_query_planner=True,
            top_k=max(base_top_k, 6),
        )
    elif intent == "multi_hop":
        settings.update(
            retrieval_strategy="planned_subquery_hybrid",
            search_mode="multi_query_hybrid",
            use_query_planner=True,
            top_k=max(base_top_k, 6),
        )
    elif intent == "aggregation":
        settings.update(
            retrieval_strategy="structured_table_metadata_first",
            search_mode="structured_first",
            use_structured_query=True,
            chunk_granularity="section",
            top_k=max(base_top_k, 24),
        )
    elif intent == "graphrag_global":
        settings.update(
            retrieval_strategy="graphrag_global",
            search_mode="hybrid",
            use_query_planner=False,
            use_reranker=False,
            chunk_granularity="document",
            top_k=max(base_top_k, 8),
        )
    elif intent == "conflict_check":
        settings.update(
            retrieval_strategy="competing_claims_hybrid",
            use_conflict_checker=True,
            top_k=max(base_top_k, 8),
        )
    elif intent == "troubleshooting":
        settings.update(
            retrieval_strategy="symptom_cause_fix_hybrid",
            use_query_planner=True,
            chunk_granularity="section",
            top_k=max(base_top_k, 6),
        )
    elif intent == "document_navigation":
        settings.update(
            retrieval_strategy="source_metadata_lookup",
            search_mode="metadata",
            chunk_granularity="section",
            top_k=max(base_top_k, 6),
        )
    elif intent == "out_of_scope":
        settings.update(
            needs_retrieval=False,
            retrieval_strategy="abstain_without_retrieval",
            use_reranker=False,
            top_k=0,
            allow_abstain=True,
        )
    if intent in {"temporal", "temporal_comparison", "temporal_factual"} or (
        temporal_scope and intent in {"aggregation", "comparative_summary", "troubleshooting", "troubleshooting_procedure"}
    ):
        settings["use_temporal_filter"] = True
        filters = dict(settings["filters"])
        if target_date is not None:
            filters["target_date"] = target_date
        settings["filters"] = filters
    return settings


def _is_section_scoped_summary(query: str) -> bool:
    normalized = query.lower()
    return any(term in normalized for term in ("section", "chapter", "page", "paragraph", "requirements"))


def _has_temporal_scope(query: str, target_date: str | None) -> bool:
    if target_date is not None:
        return True
    normalized = query.lower()
    return any(
        term in normalized
        for term in (
            "latest",
            "current",
            "currently",
            "as of",
            "historical",
            "previous",
            "old",
            "before",
            "after",
            "changed",
            "updated",
            "update",
            "version",
            "still valid",
        )
    )


def _risk_level(intent: RouteIntent) -> RiskLevel:
    if intent in {"aggregation", "graphrag_global", "conflict_check", "out_of_scope"}:
        return "high"
    if intent in {
        "comparison",
        "temporal",
        "temporal_comparison",
        "multi_hop",
        "troubleshooting",
        "troubleshooting_procedure",
        "comparative_summary",
        "document_navigation",
    }:
        return "medium"
    return "low"
