"""Session, source, intent, and query-planning graph nodes."""

from __future__ import annotations

from dataclasses import replace

from rag.query.history_access import context_is_available
from rag.query.abbreviations import resolve_abbreviation_query
from rag.query.answering.reasoning import (
    extract_temporal_scope_with_reasoning,
    plan_sub_queries_with_reasoning,
)
from rag.query.cancellation import cancellation_token_from_context
from rag.query.routing.intent_router import route_query
from rag.query.routing.conversation_resolution import resolve_conversation
from rag.query.chat_history_models import (
    ChatHistoryRequestConflict,
    context_turn_for_message_id,
)
from rag.query.routing.routing_logs import (
    log_conversation_resolution,
    log_route_decision,
)
from rag.query.sources.source_resolution import (
    resolve_query_source,
    source_decision_from_evidence_plan,
)

from ..schemas import (
    QuerySourceClarification,
    QuerySourceClarificationOption,
    RAGResponse,
)
from ..state import QueryContext, active_query
from .node_support import _apply_route_plan, _mark_execution, _raise_if_cancelled


class RoutingNodes:
    def session_memory(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        reply_to_turn_id = ctx["request"].reply_to_turn_id
        turns = (
            self.chat_history_repo.load_recent_context_turns(
                user_id=ctx["user"].user_id,
                permission_version=ctx["user"].permission_version,
                session_id=ctx["session_id"],
                limit=8,
            )
            if self.context_resolver_enabled
            else []
        )
        if reply_to_turn_id:
            # ponytail: reuse the existing session read; add a targeted lookup only if long chats make this measurable.
            session = self.chat_history_repo.get_session(
                user_id=ctx["user"].user_id,
                permission_version=ctx["user"].permission_version,
                session_id=ctx["session_id"],
            )
            reply_turn = (
                context_turn_for_message_id(session.turns, reply_to_turn_id)
                if session is not None
                else None
            )
            if reply_turn is None:
                raise ChatHistoryRequestConflict(
                    "reply target was not found in this chat"
                )
            canonical_turn_id = reply_turn.get("turn_id")
            if not isinstance(canonical_turn_id, str) or not canonical_turn_id:
                raise ChatHistoryRequestConflict(
                    "reply target does not identify a complete exchange"
                )
            if self.context_resolver_enabled:
                turns = [
                    turn
                    for turn in turns
                    if turn.get("turn_id") != canonical_turn_id
                ]
                turns.append(reply_turn)
            else:
                turns = [reply_turn]
            ctx["reply_context_turn_id"] = canonical_turn_id
        ctx["session_turns"] = [turn for turn in turns if context_is_available(
            turn, user=ctx["user"], documents=self.document_repo)]
        return ctx

    def conversation_resolver(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        resolution = resolve_conversation(
            ctx["request"].query,
            ctx["session_turns"],
            client=self.ollama,
            model=self.routing_model,
            enabled=self.context_resolver_enabled,
            reply_to_turn_id=ctx.get("reply_context_turn_id"),
            has_explicit_scope=bool(
                ctx["request"].document_ids
                or ctx["request"].effective_query_source_ids
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
            graph_enabled=self.graph_enabled,
            router_client=self.ollama,
            router_model=self.routing_model,
            cancellation_token=cancellation_token_from_context(ctx),
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
        _mark_execution(ctx, "source_resolver", decision.router_mode, detail)
        return ctx

    def source_clarifier(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        decision = ctx.get("source_decision")
        route = decision.database_route if decision is not None else None
        if route is None or route.outcome == "selected":
            raise RuntimeError(
                "source clarifier requires an unresolved database route"
            )
        options = [
            QuerySourceClarificationOption(
                source_id=candidate.source_id,
                name=candidate.name,
                description=candidate.description or None,
            )
            for candidate in route.candidates
        ]
        question = route.clarification_question or (
            "Which database source should I use for this question?"
        )
        has_options = bool(options)
        ctx["intent"] = "conversational"
        ctx["faithfulness_score"] = 0.0
        ctx["faithfulness_status"] = "skipped"
        ctx["unfounded_claims"] = []
        ctx["response"] = RAGResponse(
            trace_id=ctx["trace_id"],
            answer=(
                question
                if has_options
                else "No authorized Live DB source is available for this question."
            ),
            answer_status="clarification" if has_options else "abstained",
            source_clarification=(
                QuerySourceClarification(question=question, options=options)
                if has_options
                else None
            ),
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
            source_mode=decision.resolved_mode if decision is not None else None,
            source_decision_reason=route.reason,
        )
        _mark_execution(
            ctx,
            "source_clarifier",
            route.router_mode,
            f"{route.outcome},candidates={len(options)},reason={route.reason}",
        )
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
            source_candidates=ctx.get("source_candidates"),
        )
        source_decision = ctx.get("source_decision")
        if source_decision is not None:
            source_decision = source_decision_from_evidence_plan(
                source_decision,
                plan.evidence_plan,
                ctx.get("source_candidates"),
            )
            ctx["source_decision"] = source_decision
            ctx["execution_details"]["source_resolver"] = (
                f"{source_decision.resolved_mode}:{source_decision.reason},"
                f"assignments={sum(len(need.assignments) for need in (plan.evidence_plan.needs if plan.evidence_plan else ())) }"
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
