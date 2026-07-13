"""SSE event formatting and graph progress streaming."""

from __future__ import annotations

import json
from collections.abc import Generator, Iterator
from time import perf_counter

from .schemas import QueryStreamEvent, RAGResponse
from .cancellation import call_with_optional_cancellation, cancellation_token_from_context
from .state import QueryContext, finalize_response_node_timings, record_node_timing
from .graph import route_intent, route_output, route_verifier
from .nodes import QueryNodes
from .routing_logs import log_node_timing
from .sources import sources_from_hits
from .synthesis import (
    build_conflict_answer,
    build_rag_response,
    conflict_sources,
    ensure_answer_has_citation,
    merge_sources,
    prepare_synthesis_input,
    response_sources,
)


def format_sse(event: QueryStreamEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data)}\n\n"


def stream_graph(ctx: QueryContext, nodes: QueryNodes) -> Iterator[QueryStreamEvent]:
    _raise_if_cancelled(ctx)
    yield QueryStreamEvent(event="trace", data={"trace_id": ctx["trace_id"], "session_id": ctx["session_id"]})
    yield _node_event("session_memory")
    ctx = _run("session_memory", ctx, nodes.session_memory)
    yield _node_event("source_resolver")
    ctx = _run("source_resolver", ctx, nodes.source_resolver)
    yield _node_event("intent_router")
    ctx = _run("intent_router", ctx, nodes.intent_router)
    yield QueryStreamEvent(event="intent", data={"intent": ctx["intent"]})
    intent_route = route_intent(ctx)
    if intent_route == "respond":
        yield _node_event("evidence_builder")
        ctx = _run("evidence_builder", ctx, nodes.evidence_builder)
        yield _node_event("synthesizer")
        ctx = yield from _stream_timed_synthesizer(ctx, nodes)
        ctx = yield from _stream_response_tail(ctx, nodes)
        return
    if intent_route == "plan":
        ctx = _run("query_planner", ctx, nodes.query_planner)
        yield _node_event("query_planner", ctx=ctx)
    elif intent_route == "artifact":
        ctx = _run("artifact_planner", ctx, nodes.artifact_planner)
        yield _node_event("artifact_planner", ctx=ctx)
    while True:
        yield _node_event("abac_retriever")
        ctx = _run("abac_retriever", ctx, nodes.abac_retriever)
        yield _node_event("reranker")
        ctx = _run("reranker", ctx, nodes.reranker)
        ctx = _run("verifier", ctx, nodes.verifier)
        yield _node_event("verifier", ctx=ctx)
        if route_verifier(ctx) == "retry":
            yield QueryStreamEvent(event="warning", data={"code": "verifier_retry", "retry_count": ctx["retry_count"]})
            continue
        if route_verifier(ctx) == "pass":
            ctx = _run("temporal_resolver", ctx, nodes.temporal_resolver)
            yield _node_event("temporal_resolver", ctx=ctx)
            ctx = _run("contradiction_detector", ctx, nodes.contradiction_detector)
            yield _node_event("contradiction_detector", ctx=ctx)
        break
    yield _node_event("evidence_builder")
    ctx = _run("evidence_builder", ctx, nodes.evidence_builder)
    for source in sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query):
        yield QueryStreamEvent(event="source", data=source.model_dump())
    if route_output(ctx) == "artifact":
        yield _node_event("artifact_composer")
        ctx = _run("artifact_composer", ctx, nodes.artifact_composer)
        yield _node_event("artifact_content_validator")
        ctx = _run("artifact_content_validator", ctx, nodes.artifact_content_validator)
        yield _node_event("artifact_generator")
        ctx = _run("artifact_generator", ctx, nodes.artifact_generator)
        yield QueryStreamEvent(event="token", data={"text": ctx["response"].answer})
        for artifact in ctx["response"].artifacts:
            yield QueryStreamEvent(event="artifact", data=artifact.model_dump())
        yield _node_event("response_serializer")
        ctx = _run("response_serializer", ctx, nodes.response_serializer)
        ctx = finalize_response_node_timings(ctx)
        yield QueryStreamEvent(event="done", data=ctx["response"].model_dump())
        return
    yield _node_event("synthesizer")
    ctx = yield from _stream_timed_synthesizer(ctx, nodes)
    ctx = yield from _stream_response_tail(ctx, nodes)


def _stream_response_tail(ctx: QueryContext, nodes: QueryNodes) -> Generator[QueryStreamEvent, None, QueryContext]:
    if _should_defer_faithfulness(ctx, nodes):
        yield _node_event("response_serializer")
        ctx = _run("response_serializer", ctx, nodes.response_serializer)
        ctx = _refresh_response_metadata(ctx)
        response = ctx["response"]
        yield from _terminal_warnings(response, nodes, include_faithfulness=False)
        yield QueryStreamEvent(event="done", data=response.model_dump())

        yield _node_event("faithfulness_checker")
        ctx = _run("faithfulness_checker", ctx, nodes.faithfulness_checker)
        ctx = _refresh_response_metadata(ctx)
        response = ctx["response"]
        yield from _faithfulness_warnings(response, nodes)
        yield QueryStreamEvent(event="verified", data=response.model_dump())
        return ctx

    yield _node_event("faithfulness_checker")
    ctx = _run("faithfulness_checker", ctx, nodes.faithfulness_checker)
    response = ctx["response"]
    yield _node_event("artifact_generator")
    ctx = _run("artifact_generator", ctx, nodes.artifact_generator)
    response = ctx["response"]
    for artifact in response.artifacts:
        yield QueryStreamEvent(event="artifact", data=artifact.model_dump())
    yield _node_event("response_serializer")
    ctx = _run("response_serializer", ctx, nodes.response_serializer)
    ctx = _refresh_response_metadata(ctx)
    response = ctx["response"]
    yield from _terminal_warnings(response, nodes, include_faithfulness=True)
    yield QueryStreamEvent(event="done", data=response.model_dump())
    return ctx


def _should_defer_faithfulness(ctx: QueryContext, nodes: QueryNodes) -> bool:
    return (
        bool(nodes.config.rag_defer_faithfulness)
        and nodes.should_run_faithfulness(ctx)
        and not _artifact_generation_requested(ctx)
    )


def _artifact_generation_requested(ctx: QueryContext) -> bool:
    artifact_request = ctx.get("artifact_request")
    return artifact_request is not None and not artifact_request.needs_clarification


def _refresh_response_metadata(ctx: QueryContext) -> QueryContext:
    return finalize_response_node_timings(ctx)


def _terminal_warnings(
    response: RAGResponse,
    nodes: QueryNodes,
    *,
    include_faithfulness: bool,
) -> Iterator[QueryStreamEvent]:
    if include_faithfulness:
        yield from _faithfulness_warnings(response, nodes)
    if response.conflict_flag:
        yield QueryStreamEvent(event="warning", data={"code": "conflicting_sources"})
    if response.degraded:
        yield QueryStreamEvent(event="warning", data={"code": response.degraded_reason or "degraded"})


def _faithfulness_warnings(response: RAGResponse, nodes: QueryNodes) -> Iterator[QueryStreamEvent]:
    if (
        response.faithfulness_status == "checked"
        and response.faithfulness_score < nodes.config.rag_faithfulness_threshold
    ):
        yield QueryStreamEvent(
            event="warning",
            data={
                "code": "low_faithfulness",
                "score": response.faithfulness_score,
                "unfounded_claims": response.unfounded_claims,
            },
        )


def _stream_timed_synthesizer(ctx: QueryContext, nodes: QueryNodes) -> Iterator[QueryStreamEvent]:
    started = perf_counter()
    result = yield from _stream_synthesizer(ctx, nodes)
    duration_ms = int((perf_counter() - started) * 1000)
    record_node_timing(result, "synthesizer", duration_ms)
    log_node_timing(result, node="synthesizer", duration_ms=duration_ms)
    return result


def _stream_synthesizer(ctx: QueryContext, nodes: QueryNodes) -> Iterator[QueryStreamEvent]:
    _raise_if_cancelled(ctx)
    ctx["node_trace"].append({"node": "synthesizer", "agent": None})
    evidence_sources = sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query)
    plan = ctx.get("route_plan")
    prepared = prepare_synthesis_input(ctx, evidence_sources)
    ctx["synthesis_profile"] = prepared.profile
    streamed_answer = False
    artifact_request = ctx.get("artifact_request")
    if artifact_request is not None and artifact_request.needs_clarification:
        available_sources = []
        answer = "What should the file cover? Please include a topic or question, and I can generate the requested file."
    elif plan is not None and not plan.needs_retrieval:
        available_sources = []
        answer = "I can only answer questions grounded in the indexed documents."
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "out_of_scope"
    elif ctx["conflict_flag"]:
        ctx["synthesis_profile"] = "conflict_check"
        available_sources = merge_sources(evidence_sources, conflict_sources(ctx["conflict_pairs"]))
        answer = build_conflict_answer(ctx["conflict_pairs"])
    elif evidence_sources:
        available_sources = prepared.sources
        chunks: list[str] = []
        chunk_stream = call_with_optional_cancellation(
            nodes.ollama.stream_answer,
            cancellation_token_from_context(ctx),
            question=prepared.question,
            contexts=prepared.contexts,
            profile=prepared.profile,
        )
        for chunk in chunk_stream:
            _raise_if_cancelled(ctx)
            chunks.append(chunk)
            yield QueryStreamEvent(event="token", data={"text": chunk})
        raw_answer = "".join(chunks)
        answer = ensure_answer_has_citation(raw_answer, available_sources)
        streamed_answer = True
        # Token events are append-only; non-prefix corrections are delivered by the authoritative done snapshot.
        if answer.startswith(raw_answer):
            citation_suffix = answer[len(raw_answer):]
            if citation_suffix:
                yield QueryStreamEvent(event="token", data={"text": citation_suffix})
    else:
        available_sources = []
        answer = "No accessible current sources were found for this query."
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "no_indexed_sources"
    if not streamed_answer:
        answer = ensure_answer_has_citation(answer, available_sources)
        yield QueryStreamEvent(event="token", data={"text": answer})
    ctx["response"] = build_rag_response(
        ctx,
        answer=answer,
        sources=response_sources(answer, available_sources),
    )
    return ctx


def _run(node: str, ctx: QueryContext, fn, *, agent: str | None = None) -> QueryContext:
    _raise_if_cancelled(ctx)
    ctx["node_trace"].append({"node": node, "agent": agent})
    started = perf_counter()
    result = fn(ctx)
    duration_ms = int((perf_counter() - started) * 1000)
    record_node_timing(result, node, duration_ms)
    log_node_timing(result, node=node, duration_ms=duration_ms)
    _raise_if_cancelled(result)
    return result


def _node_event(node: str, agent: str | None = None, ctx: QueryContext | None = None) -> QueryStreamEvent:
    data: dict[str, object] = {"node": node}
    if agent is not None:
        data["agent"] = agent
    if ctx is not None:
        mode = ctx["execution_modes"].get(node)
        detail = ctx["execution_details"].get(node)
        if mode:
            data["execution_mode"] = mode
        if detail:
            data["detail"] = detail
    return QueryStreamEvent(event="trace", data=data)


def _raise_if_cancelled(ctx: QueryContext) -> None:
    token = cancellation_token_from_context(ctx)
    if token is not None:
        token.raise_if_cancelled()
