"""Retrieval, reranking, verification, and evidence graph nodes."""

from __future__ import annotations

from ...graphrag.graphrag_retriever import GraphRAGRetriever
from ..artifact_pipeline import assess_artifact_evidence
from ..cancellation import cancellation_token_from_context
from ..conflicts import apply_conflict_detection, apply_hybrid_disagreement_detection
from ..evidence_quality import EvidenceQuality, assess_evidence_quality
from ..query_intent import rewrite_for_retry
from ..query_retrieval import merge_artifact_protected_hits, merge_route_protected_hits
from ..reasoning import rewrite_query_with_reasoning
from ..reranker import rerank_hits
from ..routing_evidence import inspect_evidence_for_reroute
from ..routing_logs import log_artifact_evidence, log_retrieval_summary, log_verifier_decision
from ..sources import build_evidence_hits
from ..state import QueryContext
from .node_support import (
    _apply_route_plan,
    _mark_execution,
    _raise_if_cancelled,
    _retrieval_execution_summary,
    _retrieval_retry_limit_reached,
    _should_promote_parent_context,
)


class RetrievalNodes:
    def abac_retriever(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        plan = ctx.get("route_plan")
        if plan is not None and plan.retrieval_strategy == "graphrag_global":
            result = GraphRAGRetriever(
                config=self.config,
                embedder=self.ollama,
                document_qdrant=self.qdrant,
            ).retrieve(ctx, top_k_communities=plan.top_k)
            if result.is_available:
                ctx["graphrag_communities"] = result.communities
                ctx["retrieved_hits"] = result.source_hits
                _mark_execution(
                    ctx,
                    "abac_retriever",
                    "graphrag",
                    f"communities={len(result.communities)},source_chunks={len(result.source_hits)}",
                )
                log_retrieval_summary(ctx, stage="retrieved")
                return ctx
            if "graphrag_communities" in ctx:
                del ctx["graphrag_communities"]
            ctx["degraded"] = True
            ctx["degraded_reason"] = result.degraded_reason or "graphrag_unavailable"
            _mark_execution(ctx, "abac_retriever", "graphrag_fallback", ctx["degraded_reason"])
        ctx["retrieved_hits"] = self.retrieval_service.retrieve(ctx)
        if "abac_retriever" not in ctx["execution_modes"]:
            _mark_execution(ctx, "abac_retriever", *_retrieval_execution_summary(ctx))
        log_retrieval_summary(ctx, stage="retrieved")
        return ctx

    def reranker(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        plan = ctx.get("route_plan")
        if plan is not None and not plan.use_reranker:
            log_retrieval_summary(ctx, stage="rerank_skipped", before_count=len(ctx["retrieved_hits"]))
            return ctx
        query = " ".join(ctx["sub_queries"] or [ctx["request"].query])
        original_hits = ctx["retrieved_hits"]
        ranked_hits = rerank_hits(
            query,
            original_hits,
            top_k=plan.top_k if plan else self.config.rag_top_k,
            max_candidates=self.config.rag_reranker_max_candidates,
            model_name=self.reranker_model,
            cache_dir=self.config.rag_reranker_cache_dir,
        )
        if plan is not None:
            ranked_hits = merge_route_protected_hits(
                original_hits=original_hits,
                ranked_hits=ranked_hits,
                plan=plan,
            )
        ctx["retrieved_hits"] = merge_artifact_protected_hits(
            original_hits=original_hits,
            ranked_hits=ranked_hits,
            artifact_plan=ctx.get("artifact_plan"),
        )
        log_retrieval_summary(ctx, stage="reranked", before_count=len(original_hits))
        return ctx

    def verifier(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        plan = ctx.get("route_plan")
        if plan is not None:
            inspection = inspect_evidence_for_reroute(
                plan,
                ctx["retrieved_hits"],
                reroute_count=ctx["route_reroute_count"],
            )
            if inspection.should_reroute and inspection.next_plan is not None:
                _apply_route_plan(ctx, inspection.next_plan)
                ctx["route_reroute_count"] += 1
                ctx["verifier_decision"] = "retry"
                _mark_execution(ctx, "verifier", "deterministic")
                log_verifier_decision(ctx)
                return ctx
        artifact_plan = ctx.get("artifact_plan")
        if artifact_plan is not None:
            return self._verify_artifact_evidence(ctx, artifact_plan)
        if ctx.get("graphrag_communities") and ctx["retrieved_hits"]:
            distinct_docs = {
                str(hit.payload["doc_id"])
                for hit in ctx["retrieved_hits"]
                if hit.payload.get("doc_id") not in (None, "")
            }
            ctx["evidence_quality"] = EvidenceQuality(
                quality="supported",
                reasons=("graphrag_community_sources",),
                max_retrieval_score=max((hit.score for hit in ctx["retrieved_hits"]), default=0.0),
                max_rerank_score=None,
                query_token_coverage=1.0,
                distinct_doc_count=len(distinct_docs),
                evidence_score=1.0,
                outcome="pass",
            )
            ctx["verifier_decision"] = "pass"
            _mark_execution(ctx, "verifier", "deterministic", "graphrag_community_sources")
            log_verifier_decision(ctx)
            return ctx
        active_query = ctx["query_rewritten"][-1] if ctx["query_rewritten"] else (
            plan.resolved_query if plan else ctx["request"].query
        )
        quality = assess_evidence_quality(active_query, ctx["retrieved_hits"], route_plan=plan)
        ctx["evidence_quality"] = quality
        if ctx["retrieved_hits"] and not quality.is_weak:
            ctx["verifier_decision"] = "pass"
            _mark_execution(ctx, "verifier", "deterministic", ",".join(quality.reasons))
            log_verifier_decision(ctx)
            return ctx
        if ctx["retrieved_hits"]:
            ctx["verifier_decision"] = "degrade"
            ctx["degraded"] = True
            ctx["degraded_reason"] = "Insufficient relevant evidence after retrieval retries"
            _mark_execution(ctx, "verifier", "deterministic", ",".join(quality.reasons))
            log_verifier_decision(ctx)
            return ctx
        return self._retry_or_degrade_retrieval(ctx, quality)

    def _verify_artifact_evidence(self, ctx: QueryContext, artifact_plan) -> QueryContext:
        assessment = assess_artifact_evidence(
            artifact_plan,
            ctx["retrieved_hits"],
            document_ids=ctx["request"].document_ids,
        )
        ctx["artifact_evidence"] = assessment.units
        ctx["artifact_coverage"] = assessment.coverage
        log_artifact_evidence(ctx)
        relevant_keys = {(unit.doc_id, unit.chunk_id) for unit in assessment.units}
        ctx["retrieved_hits"] = [
            hit
            for hit in ctx["retrieved_hits"]
            if (
                str(hit.payload.get("doc_id", hit.point_id)),
                str(hit.payload.get("chunk_id", hit.point_id)),
            )
            in relevant_keys
        ]
        rerank_scores = [
            float(score)
            for hit in ctx["retrieved_hits"]
            if isinstance((score := hit.payload.get("_rerank_score")), int | float)
        ]
        quality = EvidenceQuality(
            quality="weak" if assessment.is_weak else "supported",
            reasons=(
                ("artifact_no_relevant_evidence",)
                if assessment.is_weak
                else (f"artifact_coverage_{assessment.coverage.status}",)
            ),
            max_retrieval_score=max((hit.score for hit in ctx["retrieved_hits"]), default=0.0),
            max_rerank_score=max(rerank_scores) if rerank_scores else None,
            query_token_coverage=assessment.relevance_coverage,
            distinct_doc_count=len({unit.doc_id for unit in assessment.units}),
            evidence_score=assessment.relevance_coverage,
            outcome="degrade" if assessment.is_weak else "pass",
        )
        ctx["evidence_quality"] = quality
        if not assessment.is_weak:
            ctx["verifier_decision"] = "pass"
            _mark_execution(ctx, "verifier", "deterministic", ",".join(quality.reasons))
            log_verifier_decision(ctx)
            return ctx
        return self._retry_or_degrade_retrieval(ctx, quality)

    def _retry_or_degrade_retrieval(self, ctx: QueryContext, quality) -> QueryContext:
        detail = ",".join(quality.reasons)
        if _retrieval_retry_limit_reached(
            ctx,
            max_retries=self.config.rag_retrieval_max_retries,
        ):
            ctx["verifier_decision"] = "degrade"
            ctx["degraded"] = True
            ctx["degraded_reason"] = "Insufficient relevant evidence after retrieval retries"
            ctx["retrieved_hits"] = []
            _mark_execution(ctx, "verifier", "deterministic", detail)
            log_verifier_decision(ctx)
            return ctx
        fallback = rewrite_for_retry(ctx["request"].query, ctx["retry_count"])
        rewrite_mode = "deterministic"
        rewrite_detail = None
        rewritten = fallback
        artifact_plan = ctx.get("artifact_plan")
        structured_artifact = (
            artifact_plan is not None
            and artifact_plan.primary_operation in {"enumerate", "extract"}
        )
        if self.config.rag_query_rewrite_llm_enabled and not structured_artifact:
            rewrite = rewrite_query_with_reasoning(
                ollama=self.ollama,
                model=self.reasoning_model,
                query=ctx["request"].query,
                retry_count=ctx["retry_count"],
                fallback=fallback,
                cancellation_token=cancellation_token_from_context(ctx),
            )
            rewritten = rewrite.values[0]
            rewrite_mode = rewrite.mode
            rewrite_detail = rewrite.detail
        ctx["query_rewritten"].append(rewritten)
        ctx["sub_queries"] = [rewritten]
        ctx["retrieved_hits"] = []
        ctx["retry_count"] += 1
        ctx["verifier_decision"] = "retry"
        if rewrite_detail:
            detail = f"{detail},{rewrite_detail}"
        _mark_execution(ctx, "verifier", rewrite_mode, detail)
        log_verifier_decision(ctx)
        return ctx

    def temporal_resolver(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if not ctx["is_current_only"]:
            ctx["execution_modes"].setdefault("temporal_resolver", "deterministic")
        if ctx["is_current_only"]:
            ctx["retrieved_hits"] = [
                hit for hit in ctx["retrieved_hits"] if hit.payload.get("is_current", True) is True
            ]
            ctx["execution_modes"].setdefault("temporal_resolver", "deterministic")
        return ctx

    def contradiction_detector(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        plan = ctx.get("route_plan")
        if plan is None or plan.use_conflict_checker:
            ctx["conflict_checker_used"] = True
            _mark_execution(ctx, "contradiction_detector", "deterministic")
            ctx = apply_conflict_detection(ctx, self.conflict_checker, self.qdrant)
        if self.config.rag_hybrid_disagreement_detector_enabled:
            before = ctx["conflict_flag"]
            ctx = apply_hybrid_disagreement_detection(ctx)
            if ctx["conflict_flag"] and not before:
                _mark_execution(ctx, "contradiction_detector", "deterministic", "hybrid_source_disagreement")
        return ctx

    def evidence_builder(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if "artifact_plan" in ctx:
            return ctx
        plan = ctx.get("route_plan")
        ctx["retrieved_hits"] = build_evidence_hits(
            ctx["retrieved_hits"],
            token_budget=ctx["token_budget"],
            limit=plan.top_k if plan else self.config.rag_top_k,
            broader_table_context=_should_promote_parent_context(plan),
            query=" ".join(ctx.get("sub_queries") or [ctx["request"].query]),
        )
        return ctx
