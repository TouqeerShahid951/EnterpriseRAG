"""Production route-plan builder for the query graph."""

from __future__ import annotations

from rag.query.cancellation import QueryCancellationToken, QueryCancelled
from rag.query.http import ServiceRequestError
from rag.query.retrieval.retrieval_plans import retrieval_settings_for
from rag.query.routing.routing_models import QuerySignals, RouteMethod, RoutePenalty, RoutePlan, RuleRouteResult, public_intent_for
from rag.query.routing.routing_rules import LLM_VERIFIER_FLOOR, score_route_rules, should_call_llm_verifier
from rag.query.routing.routing_signals import extract_query_signals
from rag.query.routing.routing_verifier import RouteVerifierDecision, verify_route_with_llm


def route_query(
    query: str,
    *,
    turns: list[dict[str, object]],
    base_top_k: int,
    llm_verifier: object | None = None,
    verifier_model: str | None = None,
    verifier_enabled: bool = True,
    query_planner_enabled: bool = True,
    cancellation_token: QueryCancellationToken | None = None,
) -> tuple[RoutePlan, QuerySignals]:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    signals = extract_query_signals(query, turns)
    rule_result = score_route_rules(signals)
    verifier_decision: RouteVerifierDecision | None = None
    verifier_penalty: RoutePenalty | None = None
    if verifier_enabled and should_call_llm_verifier(rule_result) and llm_verifier is not None:
        try:
            verifier_decision = verify_route_with_llm(
                llm_verifier,
                model=verifier_model,
                signals=signals,
                candidate_scores=rule_result.raw_scores,
                cancellation_token=cancellation_token,
            )
        except QueryCancelled:
            raise
        except (TypeError, ValueError, RuntimeError, ServiceRequestError):
            verifier_penalty = RoutePenalty(None, "llm_verifier_failed", -0.20)

    if verifier_decision is not None:
        plan = _plan_from_verifier(verifier_decision, signals, rule_result, base_top_k, query_planner_enabled)
    elif rule_result.confidence < LLM_VERIFIER_FLOOR and rule_result.intent != "conversational_followup":
        plan = _fallback_plan(signals, rule_result, base_top_k, verifier_penalty, query_planner_enabled)
    else:
        plan = _plan_from_rules(signals, rule_result, base_top_k, verifier_penalty, query_planner_enabled)
    return plan, signals


def _plan_from_rules(
    signals: QuerySignals,
    rule_result: RuleRouteResult,
    base_top_k: int,
    verifier_penalty: RoutePenalty | None,
    query_planner_enabled: bool,
) -> RoutePlan:
    penalties = rule_result.penalties + ((verifier_penalty,) if verifier_penalty else ())
    return _build_plan(
        signals,
        intent=rule_result.intent,
        secondary_intents=rule_result.secondary_intents,
        confidence=rule_result.confidence,
        route_method="rules" if verifier_penalty is None else "fallback",
        base_top_k=base_top_k,
        debug_reason=rule_result.debug_reason,
        rule_hits=rule_result.rule_hits,
        penalties=penalties,
        margin=rule_result.margin,
        query_planner_enabled=query_planner_enabled,
    )


def _plan_from_verifier(
    verifier_decision: RouteVerifierDecision,
    signals: QuerySignals,
    rule_result: RuleRouteResult,
    base_top_k: int,
    query_planner_enabled: bool,
) -> RoutePlan:
    return _build_plan(
        signals,
        intent=verifier_decision.intent,
        secondary_intents=verifier_decision.secondary_intents,
        confidence=verifier_decision.confidence,
        route_method="llm_verifier",
        base_top_k=base_top_k,
        debug_reason=verifier_decision.debug_reason,
        rule_hits=rule_result.rule_hits,
        penalties=rule_result.penalties,
        margin=rule_result.margin,
        query_planner_enabled=query_planner_enabled,
    )


def _fallback_plan(
    signals: QuerySignals,
    rule_result: RuleRouteResult,
    base_top_k: int,
    verifier_penalty: RoutePenalty | None,
    query_planner_enabled: bool,
) -> RoutePlan:
    penalties = rule_result.penalties + ((verifier_penalty,) if verifier_penalty else ())
    return _build_plan(
        signals,
        intent="general_rag",
        secondary_intents=(),
        confidence=min(rule_result.confidence, 0.54),
        route_method="fallback",
        base_top_k=base_top_k,
        debug_reason=f"safe fallback: {rule_result.debug_reason}",
        rule_hits=rule_result.rule_hits,
        penalties=penalties,
        margin=rule_result.margin,
        query_planner_enabled=query_planner_enabled,
    )


def _build_plan(
    signals: QuerySignals,
    *,
    intent,
    secondary_intents,
    confidence: float,
    route_method: RouteMethod,
    base_top_k: int,
    debug_reason: str,
    rule_hits,
    penalties,
    margin: float,
    query_planner_enabled: bool,
) -> RoutePlan:
    settings = retrieval_settings_for(intent, query=signals.resolved_query, base_top_k=base_top_k)
    return RoutePlan(
        original_query=signals.original_query,
        resolved_query=signals.resolved_query,
        intent=intent,
        secondary_intents=tuple(secondary_intents),
        confidence=confidence,
        route_method=route_method,
        needs_retrieval=bool(settings["needs_retrieval"]),
        retrieval_strategy=str(settings["retrieval_strategy"]),
        search_mode=settings["search_mode"],  # type: ignore[arg-type]
        use_query_planner=bool(settings["use_query_planner"]) and query_planner_enabled,
        use_reranker=bool(settings["use_reranker"]),
        use_conversation_memory=signals.use_conversation_memory,
        use_temporal_filter=bool(settings["use_temporal_filter"]),
        use_conflict_checker=bool(settings["use_conflict_checker"]),
        use_structured_query=bool(settings["use_structured_query"]),
        chunk_granularity=settings["chunk_granularity"],  # type: ignore[arg-type]
        top_k=int(settings["top_k"]),
        filters=dict(settings["filters"]),
        allow_abstain=bool(settings["allow_abstain"]),
        risk_level=settings["risk_level"],  # type: ignore[arg-type]
        debug_reason=debug_reason,
        rule_hits=tuple(rule_hits),
        penalties=tuple(penalties),
        public_intent=public_intent_for(intent),
        margin=margin,
    )
