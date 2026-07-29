"""Response synthesis, faithfulness, and session-persistence graph nodes."""

from __future__ import annotations

from time import perf_counter

from ...graphrag.graphrag_synthesizer import synthesize_graphrag_response
from ..cancellation import cancellation_token_from_context
from rag.query.answering.faithfulness import (
    FAITHFULNESS_CHECK_FAILED,
    attributed_sources,
    evaluate_faithfulness,
    ordered_answer_covers_question,
    screen_faithfulness,
    structured_retrieval_attributed_sources,
    verify_cited_claims,
)
from rag.query.routing.routing_logs import log_faithfulness_result, log_route_outcome
from ..state import QueryContext
from rag.query.answering.synthesis import synthesize_response
from .node_support import (
    _mark_execution,
    _raise_if_cancelled,
)


_UNVERIFIED_ANSWER = (
    "I found related evidence, but I could not verify a sufficiently supported "
    "answer to this question."
)


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
        if not self.should_run_faithfulness(ctx):
            ctx["faithfulness_score"] = 0.0
            ctx["faithfulness_status"] = "skipped"
            ctx["unfounded_claims"] = []
            ctx["response"] = ctx["response"].model_copy(update={
                "sources": structured_retrieval_attributed_sources(
                    ctx["response"].answer, ctx["response"].sources
                ),
                "faithfulness_score": 0.0,
                "faithfulness_status": "skipped",
                "unfounded_claims": [],
            })
            _mark_execution(ctx, "faithfulness_checker", "skipped", self._faithfulness_skip_reason(ctx))
            log_faithfulness_result(ctx, failed=False)
            return ctx
        plan = ctx.get("route_plan")
        question = plan.resolved_query if plan is not None else ctx["request"].query
        result = None
        execution_mode = "ai_assisted"
        if self.faithfulness_policy == "adaptive":
            result = screen_faithfulness(
                ctx["response"],
                route_plan=plan,
                reranker_model=self.reranker_model,
                reranker_cache_dir=self.config.rag_reranker_cache_dir,
                reranker_device=getattr(
                    self.config, "rag_reranker_device", "auto"
                ),
            )
            if result is not None:
                execution_mode = "deterministic"
        if result is None:
            result = evaluate_faithfulness(
                ctx["response"],
                question=question,
                ollama=self.ollama,
                model=self.faithfulness_model,
                reranker_model=self.reranker_model,
                reranker_cache_dir=self.config.rag_reranker_cache_dir,
                reranker_device=getattr(
                    self.config, "rag_reranker_device", "auto"
                ),
                cancellation_token=cancellation_token_from_context(ctx),
            )
        execution_detail = None
        ordered_coverage = ordered_answer_covers_question(
            ctx["response"],
            question,
        )
        can_corroborate = (
            result.outcome == "unavailable"
            or (result.responsive and not result.missing_aspects)
            or ordered_coverage
        )
        if result.outcome in {"fail", "unavailable"} and can_corroborate:
            fallback = screen_faithfulness(
                ctx["response"],
                route_plan=plan,
                reranker_model=self.reranker_model,
                reranker_cache_dir=self.config.rag_reranker_cache_dir,
                reranker_device=getattr(
                    self.config, "rag_reranker_device", "auto"
                ),
            )
            sufficiency = ctx.get("evidence_sufficiency")
            if (
                fallback is None
                and plan is not None
                and plan.risk_level != "high"
                and not ctx["response"].conflict_flag
                and (
                    result.outcome == "fail"
                    or (
                        result.outcome == "unavailable"
                        and sufficiency is not None
                        and sufficiency.sufficiency == "sufficient"
                        and not sufficiency.missing_aspects
                    )
                )
            ):
                fallback = verify_cited_claims(
                    ctx["response"],
                    question=question,
                    reranker_model=self.reranker_model,
                    reranker_cache_dir=self.config.rag_reranker_cache_dir,
                    reranker_device=getattr(
                        self.config, "rag_reranker_device", "auto"
                    ),
                )
            if fallback is not None:
                execution_detail = (
                    "fallback_after_unavailable"
                    if result.outcome == "unavailable"
                    else "fallback_after_disagreement"
                )
                result = fallback
                execution_mode = "deterministic"
        validation_failed = result.outcome != "pass"
        ctx["faithfulness_score"] = result.score
        ctx["faithfulness_status"] = (
            "failed" if result.outcome == "unavailable" else "checked"
        )
        ctx["unfounded_claims"] = result.unfounded_claims
        if validation_failed:
            ctx["degraded"] = True
            ctx["degraded_reason"] = ctx["degraded_reason"] or (
                "answer_not_responsive"
                if not result.responsive
                else FAITHFULNESS_CHECK_FAILED
            )
        recovered_evidence_outage = (
            not validation_failed and _recover_evidence_sufficiency_outage(ctx)
        )
        attributed = attributed_sources(ctx["response"].sources, result)
        response_updates = {
            "sources": attributed,
            "faithfulness_score": result.score,
            "faithfulness_status": ctx["faithfulness_status"],
            "unfounded_claims": result.unfounded_claims,
            "degraded": ctx["degraded"],
            "degraded_reason": ctx["degraded_reason"],
        }
        if validation_failed:
            response_updates.update(
                answer=_UNVERIFIED_ANSWER,
                answer_status="partial",
            )
        elif (
            recovered_evidence_outage
            and ctx["response"].answer_status == "partial"
        ):
            response_updates["answer_status"] = "complete"
        ctx["response"] = ctx["response"].model_copy(update={
            **response_updates,
        })
        _mark_execution(
            ctx,
            "faithfulness_checker",
            execution_mode,
            execution_detail,
        )
        log_faithfulness_result(ctx, failed=validation_failed)
        return ctx

    def should_run_faithfulness(self, ctx: QueryContext) -> bool:
        if "response" not in ctx:
            return False
        if ctx.get("force_faithfulness_check", False):
            return True
        if self.faithfulness_policy == "never":
            return False
        return bool(ctx["response"].sources or ctx["response"].conflict_flag)

    def _faithfulness_skip_reason(self, ctx: QueryContext) -> str:
        if self.faithfulness_policy == "never":
            return "policy_disabled"
        if "response" in ctx and not ctx["response"].sources and not ctx["response"].conflict_flag:
            return "no_evidence_sources"
        return "no_factual_evidence"

    def response_serializer(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if "response" not in ctx:
            raise RuntimeError("query graph finished without a response")
        response = ctx["response"]
        log_route_outcome(ctx)
        ctx["response"] = response.model_copy(update={
            "latency_ms": max(0, int((perf_counter() - ctx["wall_time_start"]) * 1000)),
        })
        return ctx


def _recover_evidence_sufficiency_outage(ctx: QueryContext) -> bool:
    """Clear a provisional evidence-judge outage after final answer verification."""
    if ctx.get("degraded_reason") != "evidence_sufficiency_unavailable":
        return False
    if ctx["response"].coverage.completeness in {"partial", "unknown"}:
        return False
    ctx["degraded"] = False
    ctx["degraded_reason"] = None
    ctx["verifier_decision"] = "pass"
    return True
