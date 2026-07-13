"""Session, source, intent, and query-planning graph nodes."""

from __future__ import annotations

from dataclasses import replace

from ..cancellation import cancellation_token_from_context
from ..intent_router import route_query
from ..query_intent import plan_sub_queries, should_include_superseded
from ..reasoning import extract_temporal_scope_with_reasoning, plan_sub_queries_with_reasoning
from ..routing_logs import log_route_decision
from ..routing_models import RoutePlan
from ..source_resolution import resolve_query_source
from ..state import QueryContext
from .node_support import _apply_route_plan, _mark_execution, _raise_if_cancelled


class RoutingNodes:
    def session_memory(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        ctx["session_turns"] = self.session_store.load(user=ctx["user"], session_id=ctx["session_id"])
        return ctx

    def source_resolver(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        decision = resolve_query_source(
            ctx,
            config=self.config,
            llm=self.ollama,
            routing_model=self.routing_model,
            schedule_repo=self.schedule_repo,
            connector_profile_repo=self.connector_profile_repo,
            document_repo=self.document_repo,
        )
        ctx["source_decision"] = decision
        if decision.semantic_query and decision.semantic_query != ctx["request"].query:
            ctx["request"] = ctx["request"].model_copy(update={"query": decision.semantic_query})
        detail = (
            f"{decision.resolved_mode}:{decision.reason}"
            f",structured={decision.structured_score},corpus={decision.corpus_score}"
            f",source={decision.source_match_score},document={decision.document_match_score}"
            f",preferred={decision.preferred_source},router={decision.router_mode}"
        )
        _mark_execution(ctx, "source_resolver", "deterministic", detail)
        return ctx

    def intent_router(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        artifact_request = ctx.get("artifact_request")
        if artifact_request is not None and artifact_request.needs_clarification:
            plan = RoutePlan(
                original_query=artifact_request.original_query,
                resolved_query=artifact_request.original_query,
                intent="out_of_scope",
                confidence=1.0,
                route_method="rules",
                needs_retrieval=False,
                use_reranker=False,
                top_k=0,
                public_intent="conversational",
                debug_reason="artifact request missing content topic",
            )
            _apply_route_plan(ctx, plan)
            _mark_execution(ctx, "intent_router", "deterministic", "artifact_topic_required")
            return ctx
        query = ctx["request"].query
        if self.config.rag_intent_router_version != "v1":
            from ..query_intent import classify_intent, resolve_conversational_query

            ctx["intent"] = classify_intent(query)
            ctx["is_current_only"] = not should_include_superseded(query)
            if ctx["intent"] == "conversational":
                ctx["sub_queries"] = [resolve_conversational_query(query, ctx["session_turns"])]
            return ctx
        plan, signals = route_query(
            query,
            turns=ctx["session_turns"],
            base_top_k=self.config.rag_top_k,
            llm_verifier=self.ollama,
            verifier_model=self.routing_model,
            verifier_enabled=self.config.rag_route_llm_verifier_enabled,
            query_planner_enabled=self.query_planner_enabled,
            cancellation_token=cancellation_token_from_context(ctx),
        )
        _mark_execution(ctx, "intent_router", "ai_assisted" if plan.route_method == "llm_verifier" else "deterministic")
        if plan.use_temporal_filter and "target_date" not in plan.filters:
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
        active_query = ctx["query_rewritten"][-1] if ctx["query_rewritten"] else (plan.resolved_query if plan else ctx["request"].query)
        fallback = plan_sub_queries(active_query, plan.intent if plan else ctx["intent"])
        result = plan_sub_queries_with_reasoning(
            ollama=self.ollama,
            model=self.reasoning_model,
            query=active_query,
            intent=plan.intent if plan else ctx["intent"],
            fallback=fallback,
            cancellation_token=cancellation_token_from_context(ctx),
        )
        ctx["sub_queries"] = result.values
        _mark_execution(ctx, "query_planner", result.mode, result.detail)
        return ctx
