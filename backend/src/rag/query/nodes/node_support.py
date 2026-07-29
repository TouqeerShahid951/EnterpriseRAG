"""Shared state-transition helpers for query graph nodes."""

from __future__ import annotations

from ..cancellation import cancellation_token_from_context
from rag.query.routing.routing_models import RoutePlan
from ..state import QueryContext


def _apply_route_plan(ctx: QueryContext, plan: RoutePlan) -> None:
    if "initial_route_intent" not in ctx:
        ctx["initial_route_intent"] = plan.intent
    ctx["route_plan"] = plan
    ctx["intent"] = plan.public_intent
    ctx["is_current_only"] = _is_current_only_for_route(plan)
    ctx["sub_queries"] = list(plan.sub_queries or (plan.resolved_query,))


def _raise_if_cancelled(ctx: QueryContext) -> None:
    token = cancellation_token_from_context(ctx)
    if token is not None:
        token.raise_if_cancelled()


def _mark_execution(ctx: QueryContext, node: str, mode: str, detail: str | None = None) -> None:
    ctx["execution_modes"][node] = mode
    if detail:
        ctx["execution_details"][node] = detail


def _is_current_only_for_route(plan: RoutePlan) -> bool:
    if not plan.needs_retrieval:
        return True
    if _target_date_from_route(plan) is not None:
        return False
    return plan.temporal_scope == "current"


def _target_date_from_route(plan: RoutePlan) -> str | None:
    value = plan.filters.get("target_date")
    return value if isinstance(value, str) and value else None


def _should_promote_parent_context(plan: RoutePlan | None) -> bool:
    if plan is None or plan.chunk_granularity not in {"section", "document"}:
        return False
    return bool(
        set(plan.capabilities)
        & {"document_search", "document_navigation", "decomposed_search"}
        or plan.response_mode
        in {"summary", "comparison", "procedure", "conflict_analysis"}
    )


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


def _retrieval_retry_limit_reached(
    ctx: QueryContext,
    *,
    max_retries: int,
) -> bool:
    return ctx["retry_count"] >= max_retries
