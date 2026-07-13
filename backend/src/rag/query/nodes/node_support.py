"""Shared state-transition helpers for query graph nodes."""

from __future__ import annotations

from ..cancellation import cancellation_token_from_context
from ..query_intent import should_include_superseded
from ..routing_models import RoutePlan
from ..state import QueryContext


def _apply_route_plan(ctx: QueryContext, plan: RoutePlan) -> None:
    if "initial_route_intent" not in ctx:
        ctx["initial_route_intent"] = plan.intent
    ctx["route_plan"] = plan
    ctx["intent"] = plan.public_intent
    ctx["is_current_only"] = _is_current_only_for_route(plan)
    ctx["sub_queries"] = [plan.resolved_query]


def _raise_if_cancelled(ctx: QueryContext) -> None:
    token = cancellation_token_from_context(ctx)
    if token is not None:
        token.raise_if_cancelled()


def _mark_execution(ctx: QueryContext, node: str, mode: str, detail: str | None = None) -> None:
    ctx["execution_modes"][node] = mode
    if detail:
        ctx["execution_details"][node] = detail


def _response_source_types(sources: list[object]) -> list[str]:
    types: list[str] = []
    for source in sources:
        doc_id = str(getattr(source, "doc_id", "") or "")
        source_type = "database" if doc_id.startswith("connector-live-scope:") else "corpus"
        if source_type not in types:
            types.append(source_type)
    return types


def _is_current_only_for_route(plan: RoutePlan) -> bool:
    if not plan.needs_retrieval:
        return True
    if _target_date_from_route(plan) is not None:
        return False
    if plan.intent in {"temporal_comparison", "comparative_summary"}:
        return False
    if plan.use_temporal_filter and _requires_superseded_evidence(plan.resolved_query):
        return False
    return not should_include_superseded(plan.resolved_query)


def _target_date_from_route(plan: RoutePlan) -> str | None:
    value = plan.filters.get("target_date")
    return value if isinstance(value, str) and value else None


def _requires_superseded_evidence(query: str) -> bool:
    if should_include_superseded(query):
        return True
    normalized = query.lower()
    return any(
        term in normalized
        for term in (
            "after",
            "changed",
            "what changed",
            "compared",
            "difference between",
            "version",
        )
    )


def _should_promote_parent_context(plan: RoutePlan | None) -> bool:
    if plan is None or plan.chunk_granularity not in {"section", "document"}:
        return False
    return plan.intent in {
        "summarization",
        "procedural",
        "troubleshooting",
        "troubleshooting_procedure",
        "document_navigation",
        "comparison",
        "temporal_comparison",
        "comparative_summary",
        "multi_hop",
    }


def _retrieval_execution_summary(ctx: QueryContext) -> tuple[str, str]:
    live_mode = ctx["execution_modes"].get("live_sql_retriever")
    live_detail = ctx["execution_details"].get("live_sql_retriever")
    source_decision = ctx.get("source_decision")
    source_mode = str(getattr(source_decision, "resolved_mode", "") or "")
    mode = "ai_assisted" if live_mode == "ai_assisted" else "fallback" if live_mode == "fallback" else "deterministic"
    detail_parts = []
    if source_mode:
        detail_parts.append(f"source={source_mode}")
    if live_mode:
        detail_parts.append(f"live_sql={live_mode}")
    if live_detail:
        detail_parts.append(live_detail)
    detail_parts.append(f"hits={len(ctx['retrieved_hits'])}")
    return mode, ",".join(detail_parts)


def _artifact_generation_requested(ctx: QueryContext) -> bool:
    artifact_request = ctx.get("artifact_request")
    return artifact_request is not None and not artifact_request.needs_clarification


def _retrieval_retry_limit_reached(
    ctx: QueryContext,
    *,
    max_retries: int,
) -> bool:
    return ctx["retry_count"] >= max_retries
