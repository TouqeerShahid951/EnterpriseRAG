"""Query graph assembly with a deterministic fallback for tests."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from .state import QueryContext, finalize_response_node_timings, record_node_timing
from .nodes import QueryNodes
from .routing_logs import log_node_timing

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - exercised by environments without langgraph
    END = None
    StateGraph = None


class QueryGraphRunner:
    def __init__(self, nodes: QueryNodes) -> None:
        self.nodes = nodes
        self._graph = _compile_graph(nodes)

    def invoke(self, ctx: QueryContext) -> QueryContext:
        if self._graph is None:
            return finalize_response_node_timings(_invoke_without_langgraph(ctx, self.nodes))
        return finalize_response_node_timings(self._graph.invoke(ctx))


def _compile_graph(nodes: QueryNodes) -> Any | None:
    if StateGraph is None or END is None:
        return None

    graph = StateGraph(QueryContext)
    graph.add_node("session_memory", _timed_node("session_memory", nodes.session_memory))
    graph.add_node("source_resolver", _timed_node("source_resolver", nodes.source_resolver))
    graph.add_node("intent_router", _timed_node("intent_router", nodes.intent_router))
    graph.add_node("query_planner", _timed_node("query_planner", nodes.query_planner))
    graph.add_node("artifact_planner", _timed_node("artifact_planner", nodes.artifact_planner))
    graph.add_node("abac_retriever", _timed_node("abac_retriever", nodes.abac_retriever))
    graph.add_node("reranker", _timed_node("reranker", nodes.reranker))
    graph.add_node("verifier", _timed_node("verifier", nodes.verifier))
    graph.add_node("temporal_resolver", _timed_node("temporal_resolver", nodes.temporal_resolver))
    graph.add_node("contradiction_detector", _timed_node("contradiction_detector", nodes.contradiction_detector))
    graph.add_node("evidence_builder", _timed_node("evidence_builder", nodes.evidence_builder))
    graph.add_node("synthesizer", _timed_node("synthesizer", nodes.synthesizer))
    graph.add_node("artifact_composer", _timed_node("artifact_composer", nodes.artifact_composer))
    graph.add_node(
        "artifact_content_validator",
        _timed_node("artifact_content_validator", nodes.artifact_content_validator),
    )
    graph.add_node("faithfulness_checker", _timed_node("faithfulness_checker", nodes.faithfulness_checker))
    graph.add_node("artifact_generator", _timed_node("artifact_generator", nodes.artifact_generator))
    graph.add_node("response_serializer", _timed_node("response_serializer", nodes.response_serializer))

    graph.set_entry_point("session_memory")
    graph.add_edge("session_memory", "source_resolver")
    graph.add_edge("source_resolver", "intent_router")
    graph.add_conditional_edges("intent_router", route_intent, {
        "plan": "query_planner",
        "artifact": "artifact_planner",
        "retrieve": "abac_retriever",
        "respond": "evidence_builder",
    })
    graph.add_edge("query_planner", "abac_retriever")
    graph.add_edge("artifact_planner", "abac_retriever")
    graph.add_edge("abac_retriever", "reranker")
    graph.add_edge("reranker", "verifier")
    graph.add_conditional_edges("verifier", route_verifier, {
        "pass": "temporal_resolver",
        "retry": "abac_retriever",
        "degrade": "evidence_builder",
    })
    graph.add_edge("temporal_resolver", "contradiction_detector")
    graph.add_edge("contradiction_detector", "evidence_builder")
    graph.add_conditional_edges("evidence_builder", route_output, {
        "artifact": "artifact_composer",
        "answer": "synthesizer",
    })
    graph.add_edge("artifact_composer", "artifact_content_validator")
    graph.add_edge("artifact_content_validator", "artifact_generator")
    graph.add_edge("synthesizer", "faithfulness_checker")
    graph.add_edge("faithfulness_checker", "artifact_generator")
    graph.add_edge("artifact_generator", "response_serializer")
    graph.add_edge("response_serializer", END)
    return graph.compile()


def route_intent(ctx: QueryContext) -> str:
    artifact_request = ctx.get("artifact_request")
    if artifact_request is not None and not artifact_request.needs_clarification:
        return "artifact"
    plan = ctx.get("route_plan")
    if plan is not None:
        if not plan.needs_retrieval:
            return "respond"
        return "plan" if plan.use_query_planner else "retrieve"
    if ctx["intent"] in {"factual_simple", "conversational"}:
        return "retrieve"
    return "plan"


def route_verifier(ctx: QueryContext) -> str:
    return ctx["verifier_decision"]


def route_output(ctx: QueryContext) -> str:
    return "artifact" if "artifact_plan" in ctx else "answer"


def _invoke_without_langgraph(ctx: QueryContext, nodes: QueryNodes) -> QueryContext:
    ctx = _run_timed_node("session_memory", ctx, nodes.session_memory)
    ctx = _run_timed_node("source_resolver", ctx, nodes.source_resolver)
    ctx = _run_timed_node("intent_router", ctx, nodes.intent_router)
    intent_route = route_intent(ctx)
    if intent_route == "respond":
        ctx = _run_timed_node("evidence_builder", ctx, nodes.evidence_builder)
        ctx = _run_timed_node("synthesizer", ctx, nodes.synthesizer)
        ctx = _run_timed_node("faithfulness_checker", ctx, nodes.faithfulness_checker)
        ctx = _run_timed_node("artifact_generator", ctx, nodes.artifact_generator)
        return _run_timed_node("response_serializer", ctx, nodes.response_serializer)
    if intent_route == "plan":
        ctx = _run_timed_node("query_planner", ctx, nodes.query_planner)
    elif intent_route == "artifact":
        ctx = _run_timed_node("artifact_planner", ctx, nodes.artifact_planner)
    while True:
        ctx = _run_timed_node("abac_retriever", ctx, nodes.abac_retriever)
        ctx = _run_timed_node("reranker", ctx, nodes.reranker)
        ctx = _run_timed_node("verifier", ctx, nodes.verifier)
        decision = route_verifier(ctx)
        if decision == "retry":
            continue
        if decision == "pass":
            ctx = _run_timed_node("temporal_resolver", ctx, nodes.temporal_resolver)
            ctx = _run_timed_node("contradiction_detector", ctx, nodes.contradiction_detector)
        break
    ctx = _run_timed_node("evidence_builder", ctx, nodes.evidence_builder)
    if route_output(ctx) == "artifact":
        ctx = _run_timed_node("artifact_composer", ctx, nodes.artifact_composer)
        ctx = _run_timed_node("artifact_content_validator", ctx, nodes.artifact_content_validator)
        ctx = _run_timed_node("artifact_generator", ctx, nodes.artifact_generator)
        return _run_timed_node("response_serializer", ctx, nodes.response_serializer)
    ctx = _run_timed_node("synthesizer", ctx, nodes.synthesizer)
    ctx = _run_timed_node("faithfulness_checker", ctx, nodes.faithfulness_checker)
    ctx = _run_timed_node("artifact_generator", ctx, nodes.artifact_generator)
    return _run_timed_node("response_serializer", ctx, nodes.response_serializer)


def _timed_node(node: str, fn: Callable[[QueryContext], QueryContext]) -> Callable[[QueryContext], QueryContext]:
    def wrapped(ctx: QueryContext) -> QueryContext:
        return _run_timed_node(node, ctx, fn)

    return wrapped


def _run_timed_node(node: str, ctx: QueryContext, fn: Callable[[QueryContext], QueryContext]) -> QueryContext:
    started = perf_counter()
    result = fn(ctx)
    duration_ms = int((perf_counter() - started) * 1000)
    record_node_timing(result, node, duration_ms)
    log_node_timing(result, node=node, duration_ms=duration_ms)
    return result
