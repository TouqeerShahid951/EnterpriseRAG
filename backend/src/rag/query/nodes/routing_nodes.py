"""Session, source, intent, and query-planning graph nodes."""

from __future__ import annotations

from dataclasses import replace

from rag.query.abbreviations import resolve_abbreviation_query
from rag.query.answering.reasoning import (
    extract_temporal_scope_with_reasoning,
    plan_sub_queries_with_reasoning,
)
from rag.query.cancellation import cancellation_token_from_context
from rag.query.routing.intent_router import route_query
from rag.query.routing.conversation_resolution import resolve_conversation
from rag.query.routing.routing_logs import (
    log_conversation_resolution,
    log_route_decision,
)
from rag.query.sources.source_resolution import resolve_query_source

from ..schemas import RAGResponse
from ..state import QueryContext, active_query
from .node_support import _apply_route_plan, _mark_execution, _raise_if_cancelled


class RoutingNodes:
    def session_memory(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        ctx["session_turns"] = self.chat_history_repo.load_recent_context_turns(
            user_id=ctx["user"].user_id,
            permission_version=ctx["user"].permission_version,
            session_id=ctx["session_id"],
            limit=8,
        )
        return ctx

    def conversation_resolver(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        resolution = resolve_conversation(
            ctx["request"].query,
            ctx["session_turns"],
            client=self.ollama,
            model=self.routing_model,
            has_explicit_scope=bool(
                ctx["request"].document_ids or ctx["request"].query_source_id
            ),
            cancellation_token=cancellation_token_from_context(ctx),
        )
        ctx["conversation_resolution"] = resolution
        ctx["effective_query"] = resolution.effective_query
        ctx["sub_queries"] = [resolution.effective_query]
        mode = {
            "rules": "deterministic",
            "ai_assisted": "ai_assisted",
            "fallback": "fallback",
        }[resolution.method]
        _mark_execution(
            ctx,
            "conversation_resolver",
            mode,
            f"relation={resolution.relation},turns={resolution.context_turn_count}",
        )
        log_conversation_resolution(ctx)
        return ctx

    def conversation_clarifier(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        resolution = ctx.get("conversation_resolution")
        if resolution is None or resolution.relation != "ambiguous":
            raise RuntimeError("conversation clarifier requires an ambiguous resolution")
        ctx["intent"] = "conversational"
        ctx["faithfulness_score"] = 0.0
        ctx["faithfulness_status"] = "skipped"
        ctx["unfounded_claims"] = []
        ctx["response"] = RAGResponse(
            trace_id=ctx["trace_id"],
            answer=resolution.clarification_question
            or "Which earlier question or answer are you referring to?",
            answer_status="clarification",
            sources=[],
            conflict_flag=False,
            conflict_detail=None,
            faithfulness_score=0.0,
            faithfulness_status="skipped",
            unfounded_claims=[],
            intent="conversational",
            session_id=ctx["session_id"],
            latency_ms=0,
            degraded=False,
            degraded_reason=None,
        )
        _mark_execution(ctx, "conversation_clarifier", "deterministic", "ambiguous_reference")
        return ctx

    def source_resolver(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        decision = resolve_query_source(
            ctx,
            schedule_repo=self.schedule_repo,
            connector_profile_repo=self.connector_profile_repo,
            document_repo=self.document_repo,
        )
        ctx["source_decision"] = decision
        if decision.semantic_query and decision.semantic_query != active_query(ctx):
            ctx["effective_query"] = decision.semantic_query
            ctx["sub_queries"] = [decision.semantic_query]
        detail = (
            f"{decision.resolved_mode}:{decision.reason}"
            f",structured={decision.structured_score},corpus={decision.corpus_score}"
            f",source={decision.source_match_score},document={decision.document_match_score}"
            f",preferred={decision.preferred_source},confidence={decision.routing_confidence:.2f}"
            f",router={decision.router_mode}"
        )
        _mark_execution(ctx, "source_resolver", "deterministic", detail)
        return ctx

    def intent_router(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        original_query = ctx["request"].query
        query = active_query(ctx)
        if self.abbreviation_service is not None:
            try:
                query, glossary_hits, attempted = resolve_abbreviation_query(
                    ctx,
                    service=self.abbreviation_service,
                )
            except Exception:
                _raise_if_cancelled(ctx)
                ctx["degraded"] = True
                ctx["degraded_reason"] = (
                    ctx["degraded_reason"] or "abbreviation_glossary_unavailable"
                )
            else:
                if attempted:
                    ctx["abbreviation_query"] = query
                    ctx["abbreviation_glossary_hits"] = glossary_hits
                if query != original_query:
                    ctx["sub_queries"] = [query]
        plan, signals = route_query(
            query,
            turns=[],
            base_top_k=self.config.rag_top_k,
            llm_verifier=self.ollama,
            verifier_model=self.routing_model,
            verifier_enabled=True,
            query_planner_enabled=self.query_planner_enabled,
            cancellation_token=cancellation_token_from_context(ctx),
            source_decision=ctx.get("source_decision"),
        )
        resolution = ctx.get("conversation_resolution")
        uses_memory = resolution is not None and resolution.relation == "follow_up"
        plan = replace(
            plan,
            original_query=original_query,
            use_conversation_memory=uses_memory,
        )
        signals = replace(
            signals,
            original_query=original_query,
            has_session_context=bool(ctx["session_turns"]),
            use_conversation_memory=uses_memory,
            is_vague_followup=uses_memory,
        )
        _mark_execution(
            ctx,
            "intent_router",
            (
                "ai_assisted"
                if plan.route_method == "llm_planner"
                else "deterministic"
                if plan.route_method == "rules"
                else "fallback"
            ),
            plan.planner_reason,
        )
        if plan.temporal_scope == "as_of" and "target_date" not in plan.filters:
            temporal = extract_temporal_scope_with_reasoning(
                ollama=self.ollama,
                model=self.reasoning_model,
                query=signals.resolved_query,
                cancellation_token=cancellation_token_from_context(ctx),
            )
            if temporal.target_date:
                plan = replace(plan, filters={**plan.filters, "target_date": temporal.target_date})
            if temporal.mode != "deterministic":
                _mark_execution(ctx, "temporal_resolver", temporal.mode, temporal.detail)
        _apply_route_plan(ctx, plan)
        ctx["route_signals"] = signals
        log_route_decision(
            trace_id=ctx["trace_id"],
            session_id=ctx["session_id"],
            user_id=ctx["user"].user_id,
            permission_version=ctx["user"].permission_version,
            plan=plan,
        )
        return ctx

    def query_planner(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        plan = ctx.get("route_plan")
        active_query = (
            ctx["query_rewritten"][-1]
            if ctx["query_rewritten"]
            else (plan.resolved_query if plan else ctx["request"].query)
        )
        if plan is not None and plan.sub_queries:
            ctx["sub_queries"] = list(plan.sub_queries)
            _mark_execution(ctx, "query_planner", "ai_assisted", "capability_plan")
            return ctx
        result = plan_sub_queries_with_reasoning(
            ollama=self.ollama,
            model=self.reasoning_model,
            query=active_query,
            intent=plan.response_mode if plan else "lookup",
            fallback=[active_query],
            cancellation_token=cancellation_token_from_context(ctx),
        )
        ctx["sub_queries"] = result.values
        _mark_execution(ctx, "query_planner", result.mode, result.detail)
        return ctx
