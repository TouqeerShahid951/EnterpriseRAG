"""Response synthesis, faithfulness, and session-persistence graph nodes."""

from __future__ import annotations

from time import perf_counter

from ...graphrag.graphrag_synthesizer import synthesize_graphrag_response
from ..cancellation import cancellation_token_from_context
from rag.query.answering.faithfulness import FAITHFULNESS_CHECK_FAILED, attributed_sources, evaluate_faithfulness
from rag.query.routing.routing_logs import log_faithfulness_result, log_route_outcome
from ..state import QueryContext
from rag.query.answering.synthesis import synthesize_response
from .node_support import (
    _artifact_generation_requested,
    _mark_execution,
    _raise_if_cancelled,
    _response_source_types,
)


_FAITHFULNESS_ALWAYS = {"always", "all", "on", "true", "1"}
_FAITHFULNESS_NEVER = {"never", "off", "false", "0", "disabled"}
_HIGH_RISK_FAITHFULNESS_INTENTS = {
    "aggregation",
    "comparison",
    "comparative_summary",
    "conflict_check",
    "graphrag_global",
    "multi_hop",
    "procedural",
    "temporal",
    "temporal_comparison",
    "troubleshooting",
    "troubleshooting_procedure",
}


class ResponseNodes:
    def synthesizer(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if ctx.get("graphrag_communities") and ctx["retrieved_hits"]:
            return synthesize_graphrag_response(ctx, self.ollama, cancellation_token=cancellation_token_from_context(ctx))
        return synthesize_response(ctx, self.ollama, cancellation_token=cancellation_token_from_context(ctx))

    def faithfulness_checker(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if "response" not in ctx:
            raise RuntimeError("faithfulness checker requires a synthesized response")
        artifact_request = ctx.get("artifact_request")
        if artifact_request is not None and artifact_request.needs_clarification:
            ctx["faithfulness_score"] = 1.0
            ctx["faithfulness_status"] = "checked"
            ctx["unfounded_claims"] = []
            ctx["response"] = ctx["response"].model_copy(update={
                "faithfulness_score": 1.0,
                "faithfulness_status": "checked",
                "unfounded_claims": [],
            })
            _mark_execution(ctx, "faithfulness_checker", "deterministic", "clarification_response")
            log_faithfulness_result(ctx, failed=False)
            return ctx
        if not self.should_run_faithfulness(ctx):
            ctx["faithfulness_score"] = 1.0
            ctx["faithfulness_status"] = "skipped"
            ctx["unfounded_claims"] = []
            ctx["response"] = ctx["response"].model_copy(update={
                "faithfulness_score": 1.0,
                "faithfulness_status": "skipped",
                "unfounded_claims": [],
            })
            _mark_execution(ctx, "faithfulness_checker", "skipped", self._faithfulness_skip_reason(ctx))
            log_faithfulness_result(ctx, failed=False)
            return ctx
        result = evaluate_faithfulness(
            ctx["response"],
            ollama=self.ollama,
            model=self.faithfulness_model,
            reranker_model=self.reranker_model,
            reranker_cache_dir=self.config.rag_reranker_cache_dir,
            support_threshold=self.config.rag_faithfulness_threshold,
            cancellation_token=cancellation_token_from_context(ctx),
        )
        ctx["faithfulness_score"] = result.score
        ctx["faithfulness_status"] = "failed" if result.failed else "checked"
        ctx["unfounded_claims"] = result.unfounded_claims
        if result.failed:
            ctx["degraded"] = True
            ctx["degraded_reason"] = ctx["degraded_reason"] or FAITHFULNESS_CHECK_FAILED
        ctx["response"] = ctx["response"].model_copy(update={
            "sources": attributed_sources(ctx["response"].sources, result),
            "faithfulness_score": result.score,
            "faithfulness_status": ctx["faithfulness_status"],
            "unfounded_claims": result.unfounded_claims,
            "degraded": ctx["degraded"],
            "degraded_reason": ctx["degraded_reason"],
        })
        _mark_execution(ctx, "faithfulness_checker", "ai_assisted")
        log_faithfulness_result(ctx, failed=result.failed)
        return ctx

    def should_run_faithfulness(self, ctx: QueryContext) -> bool:
        if "response" not in ctx:
            return False
        artifact_request = ctx.get("artifact_request")
        if artifact_request is not None and artifact_request.needs_clarification:
            return False
        if ctx.get("force_faithfulness_check", False):
            return True
        policy = str(self.config.rag_faithfulness_policy or "high_risk").strip().lower()
        if policy in _FAITHFULNESS_NEVER:
            return False
        if _artifact_generation_requested(ctx):
            return True
        if policy in _FAITHFULNESS_ALWAYS:
            return bool(ctx["response"].sources or ctx["response"].conflict_flag or ctx["response"].degraded)
        if not ctx["response"].sources and not ctx["response"].conflict_flag:
            return False
        plan = ctx.get("route_plan")
        if ctx["degraded"] or ctx["conflict_flag"] or ctx["retry_count"] > 0 or ctx["route_reroute_count"] > 0:
            return True
        if plan is not None:
            if plan.risk_level in {"medium", "high"}:
                return True
            if plan.intent in _HIGH_RISK_FAITHFULNESS_INTENTS:
                return True
            if any(intent in _HIGH_RISK_FAITHFULNESS_INTENTS for intent in plan.secondary_intents):
                return True
        quality = ctx.get("evidence_quality")
        return bool(quality is not None and quality.is_weak)

    def _faithfulness_skip_reason(self, ctx: QueryContext) -> str:
        policy = str(self.config.rag_faithfulness_policy or "high_risk").strip().lower()
        if policy in _FAITHFULNESS_NEVER:
            return "policy_disabled"
        if "response" in ctx and not ctx["response"].sources and not ctx["response"].conflict_flag:
            return "no_evidence_sources"
        return "low_risk_route"

    def response_serializer(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if "response" not in ctx:
            raise RuntimeError("query graph finished without a response")
        response = ctx["response"]
        log_route_outcome(ctx)
        self.session_store.append(
            user=ctx["user"],
            session_id=ctx["session_id"],
            ttl_seconds=self.config.rag_session_ttl_seconds,
            turn={
                "query": ctx["request"].query,
                "answer": response.answer,
                "intent": response.intent,
                "sources": [source.model_dump() for source in response.sources],
                "source_mode": response.source_mode,
                "source_decision_reason": response.source_decision_reason,
                "preferred_source": getattr(ctx.get("source_decision"), "preferred_source", None),
                "source_types": _response_source_types(response.sources),
            },
        )
        ctx["response"] = response.model_copy(update={
            "latency_ms": max(0, int((perf_counter() - ctx["wall_time_start"]) * 1000)),
        })
        return ctx
