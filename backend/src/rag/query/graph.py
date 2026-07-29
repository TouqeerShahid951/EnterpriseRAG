"""Deterministic query orchestration."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

from .state import QueryContext, finalize_response_node_timings, record_node_timing
from .nodes import QueryNodes
from rag.query.routing.routing_logs import log_node_timing


class QueryGraphRunner:
    def __init__(self, nodes: QueryNodes) -> None:
        self.nodes = nodes

    def invoke(self, ctx: QueryContext) -> QueryContext:
        return finalize_response_node_timings(_invoke(ctx, self.nodes))


def route_intent(ctx: QueryContext) -> str:
    plan = ctx.get("route_plan")
    if plan is not None:
        if not plan.needs_retrieval:
            return "respond"
        return "plan" if plan.use_query_planner else "retrieve"
    if ctx["intent"] in {"factual_simple", "conversational"}:
        return "retrieve"
    return "plan"


def route_conversation(ctx: QueryContext) -> str:
    resolution = ctx.get("conversation_resolution")
    return "clarify" if resolution is not None and resolution.relation == "ambiguous" else "continue"


def route_verifier(ctx: QueryContext) -> str:
    return ctx["verifier_decision"]


def _invoke(ctx: QueryContext, nodes: QueryNodes) -> QueryContext:
    evidence_built = False
    ctx = _run_timed_node("session_memory", ctx, nodes.session_memory)
    ctx = _run_timed_node("conversation_resolver", ctx, nodes.conversation_resolver)
    if route_conversation(ctx) == "clarify":
        ctx = _run_timed_node(
            "conversation_clarifier", ctx, nodes.conversation_clarifier
        )
        return _run_timed_node("response_serializer", ctx, nodes.response_serializer)
    ctx = _run_timed_node("source_resolver", ctx, nodes.source_resolver)
    ctx = _run_timed_node("intent_router", ctx, nodes.intent_router)
    intent_route = route_intent(ctx)
    if intent_route == "respond":
        ctx = _run_timed_node("evidence_builder", ctx, nodes.evidence_builder)
        ctx = _run_timed_node("synthesizer", ctx, nodes.synthesizer)
        ctx = _run_timed_node("faithfulness_checker", ctx, nodes.faithfulness_checker)
        return _run_timed_node("response_serializer", ctx, nodes.response_serializer)
    if intent_route == "plan":
        ctx = _run_timed_node("query_planner", ctx, nodes.query_planner)
    while True:
        ctx = _run_timed_node("abac_retriever", ctx, nodes.abac_retriever)
        ctx = _run_timed_node("reranker", ctx, nodes.reranker)
        ctx = _run_timed_node("verifier", ctx, nodes.verifier)
        decision = route_verifier(ctx)
        if decision == "retry":
            continue
        if decision == "pass":
            ctx = _run_timed_node("temporal_resolver", ctx, nodes.temporal_resolver)
            ctx = _run_timed_node("evidence_builder", ctx, nodes.evidence_builder)
            evidence_built = True
            ctx = _run_timed_node("evidence_gate", ctx, nodes.evidence_gate)
            decision = route_verifier(ctx)
            if decision == "retry":
                continue
            if ctx["retrieved_hits"]:
                ctx = _run_timed_node(
                    "contradiction_detector",
                    ctx,
                    nodes.contradiction_detector,
                )
        break
    if not evidence_built:
        ctx = _run_timed_node("evidence_builder", ctx, nodes.evidence_builder)
    ctx = _run_timed_node("synthesizer", ctx, nodes.synthesizer)
    ctx = _run_timed_node("faithfulness_checker", ctx, nodes.faithfulness_checker)
    return _run_timed_node("response_serializer", ctx, nodes.response_serializer)


def _run_timed_node(node: str, ctx: QueryContext, fn: Callable[[QueryContext], QueryContext]) -> QueryContext:
    started = perf_counter()
    result = fn(ctx)
    duration_ms = int((perf_counter() - started) * 1000)
    record_node_timing(result, node, duration_ms)
    log_node_timing(result, node=node, duration_ms=duration_ms)
    return result
