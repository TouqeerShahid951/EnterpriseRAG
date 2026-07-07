"""LangGraph node implementations for the query path."""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter

from ...core.config import Settings
from ...graphrag.graphrag_retriever import GraphRAGRetriever
from ...graphrag.graphrag_synthesizer import synthesize_graphrag_response
from ..artifact_composer import artifact_response_summary, compose_artifact_content
from ..artifact_models import ArtifactValidation
from ..artifact_pipeline import (
    assess_artifact_evidence,
    plan_artifact_request,
    validate_artifact_content,
)
from ..artifact_service import GeneratedArtifactService, generated_artifact_service_from_settings
from ..cancellation import cancellation_token_from_context
from ..conflicts import ConflictChecker, apply_conflict_detection, apply_hybrid_disagreement_detection
from ..evidence_quality import EvidenceQuality, assess_evidence_quality
from ..faithfulness import FAITHFULNESS_CHECK_FAILED, attributed_sources, evaluate_faithfulness
from ..inference import InferenceClient
from ..qdrant import QdrantClient
from ..state import QueryContext
from ..intent_router import route_query
from ..query_intent import plan_sub_queries, rewrite_for_retry, should_include_superseded
from ..query_memory import QuerySessionStore
from ..query_retrieval import merge_artifact_protected_hits, merge_route_protected_hits
from ..reasoning import (
    extract_temporal_scope_with_reasoning,
    plan_sub_queries_with_reasoning,
    rewrite_query_with_reasoning,
)
from ..reranker import rerank_hits
from ..routing_evidence import inspect_evidence_for_reroute
from ..routing_logs import (
    log_artifact_composition,
    log_artifact_evidence,
    log_artifact_plan,
    log_artifact_result,
    log_artifact_validation,
    log_faithfulness_result,
    log_retrieval_summary,
    log_route_decision,
    log_route_outcome,
    log_verifier_decision,
)
from ..routing_models import RoutePlan
from ..sources import build_evidence_hits, sources_from_hits
from ..source_resolution import resolve_query_source
from ..synthesis import build_rag_response, synthesize_response
from ...retrieval import RetrievalService

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


class QueryNodes:
    def __init__(
        self,
        *,
        config: Settings,
        ollama: InferenceClient,
        qdrant: QdrantClient,
        session_store: QuerySessionStore,
        conflict_checker: ConflictChecker,
        artifact_service: GeneratedArtifactService | None = None,
        reasoning_model: str | None = None,
        routing_model: str | None = None,
        faithfulness_model: str | None = None,
        reranker_model: str | None = None,
        query_planner_enabled: bool | None = None,
        schedule_repo: object | None = None,
        connector_profile_repo: object | None = None,
        connector_registry: object | None = None,
        document_repo: object | None = None,
    ) -> None:
        self.config = config
        self.ollama = ollama
        self.qdrant = qdrant
        self.session_store = session_store
        self.conflict_checker = conflict_checker
        self.artifact_service = artifact_service or generated_artifact_service_from_settings(config)
        self.reasoning_model = reasoning_model or routing_model or config.rag_route_llm_verifier_model or config.ollama_chat_model
        self.routing_model = routing_model or self.reasoning_model
        self.faithfulness_model = faithfulness_model or config.rag_faithfulness_model or config.ollama_chat_model
        self.reranker_model = reranker_model or config.rag_reranker_model
        self.query_planner_enabled = config.rag_query_planner_enabled if query_planner_enabled is None else query_planner_enabled
        self.schedule_repo = schedule_repo
        self.connector_profile_repo = connector_profile_repo
        self.document_repo = document_repo
        self.retrieval_service = RetrievalService(
            config=config,
            embedder=ollama,
            vector_store=qdrant,
            schedule_repo=schedule_repo,
            connector_profile_repo=connector_profile_repo,
            connector_registry=connector_registry,
            reasoning_model=self.reasoning_model,
        )

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

    def artifact_planner(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        artifact_request = ctx.get("artifact_request")
        if artifact_request is None or artifact_request.needs_clarification:
            raise RuntimeError("artifact planner requires a complete artifact request")
        plan = plan_artifact_request(artifact_request, document_ids=ctx["request"].document_ids)
        ctx["artifact_plan"] = plan
        _mark_execution(
            ctx,
            "artifact_planner",
            "deterministic",
            f"{plan.artifact_type}:{','.join(plan.operations)}",
        )
        log_artifact_plan(ctx)
        return ctx

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
                hit_count=len(ctx["retrieved_hits"]),
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
            hit_count=len(ctx["retrieved_hits"]),
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

    def synthesizer(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if ctx.get("graphrag_communities") and ctx["retrieved_hits"]:
            return synthesize_graphrag_response(ctx, self.ollama, cancellation_token=cancellation_token_from_context(ctx))
        return synthesize_response(ctx, self.ollama, cancellation_token=cancellation_token_from_context(ctx))

    def artifact_composer(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        artifact_plan = ctx.get("artifact_plan")
        artifact_request = ctx.get("artifact_request")
        coverage = ctx.get("artifact_coverage")
        units = ctx.get("artifact_evidence", ())
        if artifact_plan is None or artifact_request is None:
            raise RuntimeError("artifact composer requires an artifact plan")
        if coverage is None or not units:
            ctx["degraded"] = True
            ctx["degraded_reason"] = ctx["degraded_reason"] or "artifact_no_relevant_evidence"
            ctx["response"] = build_rag_response(
                ctx,
                answer="No relevant authorized evidence was found for the requested artifact.",
                sources=[],
            )
            _mark_execution(ctx, "artifact_composer", "deterministic", "no_relevant_evidence")
            return ctx
        content = compose_artifact_content(
            plan=artifact_plan,
            units=units,
            coverage=coverage,
            ollama=self.ollama,
            cancellation_token=cancellation_token_from_context(ctx),
        )
        ctx["artifact_content"] = content
        mode = "deterministic" if artifact_plan.primary_operation in {"enumerate", "extract"} else "ai_assisted"
        _mark_execution(ctx, "artifact_composer", mode, ",".join(artifact_plan.operations))
        log_artifact_composition(ctx)
        ctx["response"] = build_rag_response(
            ctx,
            answer=artifact_response_summary(content, requested_formats=artifact_request.formats),
            sources=sources_from_hits(ctx["retrieved_hits"], query=artifact_plan.objective),
        )
        return ctx

    def artifact_content_validator(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        content = ctx.get("artifact_content")
        plan = ctx.get("artifact_plan")
        if "response" not in ctx:
            raise RuntimeError("artifact content validator requires a response")
        if content is None or plan is None:
            ctx["artifact_validation"] = ArtifactValidation(
                passed=False,
                support_score=0.0,
                errors=("Artifact content was not composed.",),
                warnings=(),
            )
        else:
            ctx["artifact_validation"] = validate_artifact_content(content, plan)
        validation = ctx["artifact_validation"]
        if not validation.passed:
            ctx["degraded"] = True
            ctx["degraded_reason"] = ctx["degraded_reason"] or "artifact_content_validation_failed"
        ctx["faithfulness_score"] = validation.support_score
        ctx["unfounded_claims"] = list(validation.errors)
        ctx["response"] = ctx["response"].model_copy(update={
            "faithfulness_score": validation.support_score,
            "unfounded_claims": list(validation.errors),
            "degraded": ctx["degraded"],
            "degraded_reason": ctx["degraded_reason"],
        })
        _mark_execution(
            ctx,
            "artifact_content_validator",
            "deterministic",
            "passed" if validation.passed else ",".join(validation.errors),
        )
        log_artifact_validation(ctx)
        log_faithfulness_result(ctx, failed=not validation.passed)
        return ctx

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

    def artifact_generator(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if "response" not in ctx:
            raise RuntimeError("artifact generator requires a synthesized response")
        artifact_request = ctx.get("artifact_request")
        if artifact_request is None or artifact_request.needs_clarification:
            log_artifact_result(
                ctx,
                requested=artifact_request is not None,
                skipped_reason="needs_clarification" if artifact_request is not None else "not_requested",
            )
            return ctx
        response = ctx["response"]
        if response.degraded and not response.sources:
            log_artifact_result(ctx, requested=True, skipped_reason="degraded_without_sources")
            return ctx
        validation = ctx.get("artifact_validation")
        artifact_content = ctx.get("artifact_content")
        if validation is not None and not validation.passed:
            log_artifact_result(ctx, requested=True, skipped_reason="content_validation_failed")
            return ctx
        if artifact_content is None:
            log_artifact_result(ctx, requested=True, skipped_reason="content_missing")
            return ctx
        result = self.artifact_service.create_for_response(
            artifact_request=artifact_request,
            response=response,
            artifact_content=artifact_content,
            user=ctx["user"],
            session_id=ctx["session_id"],
            trace_id=ctx["trace_id"],
        )
        degraded = ctx["degraded"]
        degraded_reason = ctx["degraded_reason"]
        if result.failures:
            degraded = True
            degraded_reason = degraded_reason or (
                "artifact_generation_failed" if not result.artifacts else "artifact_generation_partial"
            )
        ctx["degraded"] = degraded
        ctx["degraded_reason"] = degraded_reason
        ctx["response"] = ctx["response"].model_copy(update={
            "artifacts": result.artifacts,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
        })
        log_artifact_result(
            ctx,
            requested=True,
            artifact_count=len(result.artifacts),
            failure_count=len(result.failures),
            formats=[artifact.format for artifact in result.artifacts],
            failure_details=result.failure_details or (),
        )
        return ctx

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


def _apply_route_plan(ctx: QueryContext, plan: RoutePlan) -> None:
    if "initial_route_intent" not in ctx:
        ctx["initial_route_intent"] = plan.intent
    ctx["route_plan"] = plan
    ctx["intent"] = plan.public_intent
    ctx["is_current_only"] = _is_current_only_for_route(plan)
    ctx["sub_queries"] = [plan.resolved_query]


def _raise_if_cancelled(ctx: QueryContext) -> None:
    token = cancellation_token_from_context(ctx)
    if token is not None:
        token.raise_if_cancelled()


def _mark_execution(ctx: QueryContext, node: str, mode: str, detail: str | None = None) -> None:
    ctx["execution_modes"][node] = mode
    if detail:
        ctx["execution_details"][node] = detail


def _response_source_types(sources: list[object]) -> list[str]:
    types: list[str] = []
    for source in sources:
        doc_id = str(getattr(source, "doc_id", "") or "")
        source_type = "database" if doc_id.startswith("connector-live-scope:") else "corpus"
        if source_type not in types:
            types.append(source_type)
    return types


def _is_current_only_for_route(plan: RoutePlan) -> bool:
    if not plan.needs_retrieval:
        return True
    if _target_date_from_route(plan) is not None:
        return False
    if plan.intent in {"temporal_comparison", "comparative_summary"}:
        return False
    if plan.use_temporal_filter and _requires_superseded_evidence(plan.resolved_query):
        return False
    return not should_include_superseded(plan.resolved_query)


def _target_date_from_route(plan: RoutePlan) -> str | None:
    value = plan.filters.get("target_date")
    return value if isinstance(value, str) and value else None


def _requires_superseded_evidence(query: str) -> bool:
    if should_include_superseded(query):
        return True
    normalized = query.lower()
    return any(
        term in normalized
        for term in (
            "after",
            "changed",
            "what changed",
            "compared",
            "difference between",
            "version",
        )
    )


def _should_promote_parent_context(plan: RoutePlan | None) -> bool:
    if plan is None or plan.chunk_granularity not in {"section", "document"}:
        return False
    return plan.intent in {
        "summarization",
        "procedural",
        "troubleshooting",
        "troubleshooting_procedure",
        "document_navigation",
        "comparison",
        "temporal_comparison",
        "comparative_summary",
        "multi_hop",
    }


def _retrieval_execution_summary(ctx: QueryContext) -> tuple[str, str]:
    live_mode = ctx["execution_modes"].get("live_sql_retriever")
    live_detail = ctx["execution_details"].get("live_sql_retriever")
    source_decision = ctx.get("source_decision")
    source_mode = str(getattr(source_decision, "resolved_mode", "") or "")
    mode = "ai_assisted" if live_mode == "ai_assisted" else "fallback" if live_mode == "fallback" else "deterministic"
    detail_parts = []
    if source_mode:
        detail_parts.append(f"source={source_mode}")
    if live_mode:
        detail_parts.append(f"live_sql={live_mode}")
    if live_detail:
        detail_parts.append(live_detail)
    detail_parts.append(f"hits={len(ctx['retrieved_hits'])}")
    return mode, ",".join(detail_parts)


def _artifact_generation_requested(ctx: QueryContext) -> bool:
    artifact_request = ctx.get("artifact_request")
    return artifact_request is not None and not artifact_request.needs_clarification


def _retrieval_retry_limit_reached(
    ctx: QueryContext,
    *,
    max_retries: int,
) -> bool:
    return ctx["retry_count"] >= max_retries
