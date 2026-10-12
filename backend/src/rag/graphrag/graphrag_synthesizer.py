"""GraphRAG answer synthesis grounded in source chunks."""

from __future__ import annotations

from rag.query.cancellation import QueryCancellationToken
from rag.query.http import ServiceRequestError
from rag.query.ollama import estimate_answer_prompt_tokens
from rag.query.sources import citation_label, source_citation, sources_from_hits
from rag.query.state import QueryContext
from rag.query.answering.synthesis import (
    ANSWER_CONTEXT_LIMIT_REASON,
    answer_steps,
    append_context_limit_notice,
    fit_context_prompt_budget,
    is_answer_context_limit_error,
    mark_answer_context_limit,
    build_rag_response,
    ensure_answer_has_citation,
    is_global_abstention,
    response_sources,
    route_source_contexts,
)

from .qdrant import CommunitySearchHit


def synthesize_graphrag_response(
    ctx: QueryContext,
    ollama: object,
    *,
    cancellation_token: QueryCancellationToken | None = None,
) -> QueryContext:
    for _chunk in graphrag_synthesis_steps(ctx, ollama, cancellation_token=cancellation_token):
        pass
    return ctx


def graphrag_synthesis_steps(ctx: QueryContext, ollama: object, *, stream: bool = False,
                             cancellation_token: QueryCancellationToken | None = None):
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    sources = sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query)
    communities = ctx.get("graphrag_communities", [])
    if not sources or not communities:
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "graphrag_no_source_grounding"
        ctx["response"] = build_rag_response(
            ctx,
            answer="No accessible GraphRAG community evidence was found for this query.",
            sources=[],
        )
        return ctx

    available_labels = {source_citation(source) for source in sources}
    contexts = [
        *route_source_contexts(sources, profile="multi_hop"),
        *_community_contexts(communities, available_labels=available_labels),
    ]
    if not contexts:
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "graphrag_no_source_grounding"
        ctx["response"] = build_rag_response(
            ctx,
            answer="No accessible GraphRAG community evidence was found for this query.",
            sources=[],
        )
        return ctx

    question = _graphrag_question(ctx)
    contexts, _, complete = fit_context_prompt_budget(
        question=question, contexts=contexts,
        context_units=[[] for _ in contexts], profile="graphrag_global",
        token_budget=ctx["token_budget"],
    )
    sources = [source for source in sources if any(source_citation(source) in context for context in contexts)]
    ctx["synthesis_context_count"] = len(contexts)
    ctx["synthesis_context_complete"] = complete
    ctx["synthesis_estimated_prompt_tokens"] = estimate_answer_prompt_tokens(
        question=question, contexts=contexts, profile="graphrag_global",
    )
    if not complete:
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "synthesis_prompt_budget_incomplete"
    try:
        answer = yield from answer_steps(
            ollama,
            stream=stream,
            cancellation_token=cancellation_token,
            question=question,
            contexts=contexts,
            profile="graphrag_global",
        )
    except ServiceRequestError as exc:
        if not is_answer_context_limit_error(exc):
            raise
        mark_answer_context_limit(ctx)
        answer = append_context_limit_notice(ctx.get("streamed_answer", "") if stream else "")
    if is_global_abstention(answer):
        sources = []
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "graphrag_insufficient_evidence"
    ctx["citation_evidence"] = sources
    answer = ensure_answer_has_citation(answer, sources)
    if sources and not _has_source_citation(answer, sources) and ctx["degraded_reason"] != ANSWER_CONTEXT_LIMIT_REASON:
        ctx["degraded"] = True
        ctx["degraded_reason"] = ctx["degraded_reason"] or "graphrag_uncited_answer"
        answer = (
            "I found GraphRAG community evidence, but I cannot present uncited graph-level claims. "
            f"The strongest available source chunk is {source_citation(sources[0])}."
        )
    ctx["synthesis_profile"] = "graphrag_global"
    ctx["response"] = build_rag_response(
        ctx,
        answer=answer,
        sources=response_sources(answer, sources),
    )
    return ctx


def _graphrag_question(ctx: QueryContext) -> str:
    plan = ctx.get("route_plan")
    base = plan.resolved_query if plan is not None else ctx["request"].query
    return (
        f"{base}\n\n"
        "GraphRAG synthesis requirements for the assistant. Do not mention these requirements in the final answer:\n"
        "- Answer at corpus level: themes, patterns, risks, trends, recurring issues, or overview findings.\n"
        "- Community summaries are internal map context; cite only document/chunk source labels.\n"
        "- Do not make a theme-level claim unless the source chunks also support it.\n"
        "- If source chunks do not support a community-level inference, say the evidence is insufficient."
    )


def _has_source_citation(answer: str, sources) -> bool:
    return any(source_citation(source) in answer for source in sources)


def _community_contexts(
    communities: list[CommunitySearchHit],
    *,
    available_labels: set[str],
) -> list[str]:
    contexts: list[str] = []
    for hit in communities:
        summary = hit.summary
        labels = [
            citation_label(ref.doc_id, ref.chunk_id)
            for ref in summary.source_refs
            if citation_label(ref.doc_id, ref.chunk_id) in available_labels
        ]
        if not labels:
            continue
        parts = [
            labels[0],
            f"GraphRAG community map context: {summary.title}",
            summary.summary,
        ]
        if summary.important_entities:
            parts.append("Important entities: " + ", ".join(summary.important_entities[:12]))
        if summary.important_relationships:
            parts.append("Important relationships: " + "; ".join(summary.important_relationships[:8]))
        parts.append("Allowed source labels for this community: " + ", ".join(labels[:12]))
        contexts.append("\n".join(part for part in parts if part))
    return contexts
