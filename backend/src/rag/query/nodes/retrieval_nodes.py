"""Retrieval, reranking, verification, and evidence graph nodes."""

from __future__ import annotations

from dataclasses import replace
from itertools import zip_longest
from time import monotonic

from ...graphrag.graphrag_retriever import GraphRAGRetriever
from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE
from ..cancellation import cancellation_token_from_context
from rag.query.answering.conflicts import (
    apply_conflict_detection,
    apply_hybrid_disagreement_detection,
)
from rag.query.answering.evidence_sufficiency import (
    EvidenceSufficiencyResult,
    StructuralCoverage,
    evaluate_evidence_sufficiency,
    screen_evidence_sufficiency,
)
from rag.query.answering.evidence_quality import (
    EvidenceQuality,
    assess_evidence_quality,
)
from rag.query.routing.query_intent import rewrite_for_retry
from ..qdrant import SearchHit
from rag.query.answering.reasoning import rewrite_query_with_reasoning
from ..reranker import _coverage_obligations, rerank_hits_with_result
from rag.query.retrieval.retrieval_plans import retrieval_settings_for
from rag.query.retrieval.retrieval_structured import _has_structured_evidence
from rag.query.retrieval.retrieval_trace import (
    RetrievalStageName,
    RetrievalStageStatus,
    retrieval_trace_stage,
)
from rag.query.routing.routing_models import RetrievalCapability, RoutePlan
from rag.query.routing.routing_logs import log_retrieval_summary, log_verifier_decision
from rag.query.sources import build_evidence_hits, dedupe_hits
from rag.query.sources.source_evidence_selection import (
    _dedupe_keys,
    retrieval_query_slots,
)
from ..state import QueryContext
from .node_support import (
    _apply_route_plan,
    _mark_execution,
    _raise_if_cancelled,
    _retrieval_execution_summary,
    _retrieval_retry_limit_reached,
    _should_promote_parent_context,
)

_FACTUAL_RERANKER_MAX_CANDIDATES = 12
_GENERAL_RERANKER_MAX_CANDIDATES = 16
_COMPLEX_RERANKER_MAX_CANDIDATES = 20
_STRUCTURED_RERANKER_MAX_CANDIDATES = 24


def _reranker_candidate_limit(
    plan: RoutePlan | None,
    configured_limit: int,
    *,
    source_decision: object | None = None,
) -> int:
    if plan is None:
        route_limit = _GENERAL_RERANKER_MAX_CANDIDATES
    elif plan.coverage == "exhaustive" or "structured_query" in plan.capabilities:
        route_limit = _STRUCTURED_RERANKER_MAX_CANDIDATES
    elif (
        plan.response_mode in {"comparison", "conflict_analysis"}
        or set(plan.capabilities) & {"decomposed_search", "global_graph"}
    ):
        route_limit = _COMPLEX_RERANKER_MAX_CANDIDATES
    elif (
        plan.public_intent == "factual_simple"
        and plan.response_mode == "lookup"
        and plan.coverage == "focused"
    ):
        route_limit = _FACTUAL_RERANKER_MAX_CANDIDATES
    else:
        route_limit = _GENERAL_RERANKER_MAX_CANDIDATES
    if (
        source_decision is not None
        and not bool(getattr(source_decision, "explicit", False))
        and getattr(source_decision, "resolved_mode", None) == "hybrid"
        and float(getattr(source_decision, "routing_confidence", 0.0)) < 0.8
    ):
        route_limit = max(route_limit, _COMPLEX_RERANKER_MAX_CANDIDATES)
    return min(configured_limit, route_limit)


def _final_evidence_budget(
    plan: RoutePlan | None,
    *,
    configured_limit: int,
    configured_token_budget: int,
) -> tuple[int, int]:
    if plan is None:
        route_limit, route_tokens = 4, 4_000
    elif plan.coverage == "exhaustive":
        route_limit, route_tokens = 12, 12_000
    elif "structured_query" in plan.capabilities:
        route_limit, route_tokens = 8, 6_000
    elif set(plan.capabilities) & {"decomposed_search", "global_graph"}:
        route_limit, route_tokens = 8, 6_000
    elif plan.response_mode in {"comparison", "conflict_analysis"}:
        route_limit, route_tokens = 6, 6_000
    elif plan.response_mode in {"summary", "procedure"}:
        route_limit, route_tokens = 6, 5_000
    elif plan.response_mode == "explanation":
        route_limit, route_tokens = 4, 4_000
    else:
        route_limit, route_tokens = 4, 3_000
    return (
        min(configured_limit, route_limit),
        min(configured_token_budget, route_tokens),
    )


class RetrievalNodes:
    def abac_retriever(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        plan = ctx.get("route_plan")
        corpus_expansion = ctx.get("source_expansion_from") == "corpus_first"
        if not corpus_expansion:
            ctx.pop("graphrag_communities", None)
        graph_hits: list[SearchHit] = []
        graph_detail: str | None = None
        source_mode = str(
            getattr(ctx.get("source_decision"), "resolved_mode", "") or ""
        )
        if (
            plan is not None
            and "global_graph" in plan.capabilities
            and source_mode != "db_only"
            and not corpus_expansion
        ):
            result = GraphRAGRetriever(
                config=self.config,
                embedder=self.ollama,
                document_qdrant=self.qdrant,
            ).retrieve(ctx, top_k_communities=plan.top_k)
            if result.is_available:
                ctx["graphrag_communities"] = result.communities
                graph_hits = list(result.source_hits)
                graph_detail = (
                    f"communities={len(result.communities)},"
                    f"source_chunks={len(result.source_hits)}"
                )
            else:
                graph_detail = result.degraded_reason or "graphrag_unavailable"
        retrieved = self.retrieval_service.retrieve(ctx)
        ctx["retrieved_hits"] = _merge_abbreviation_glossary_hits(
            ctx,
            _merge_capability_hits(
                retrieved,
                graph_hits,
                capabilities=plan.capabilities
                if plan is not None
                else ("general_search",),
            ),
        )
        if graph_detail is not None:
            mode = "graphrag_hybrid" if graph_hits else "graphrag_fallback"
            _mark_execution(ctx, "abac_retriever", mode, graph_detail)
        elif "abac_retriever" not in ctx["execution_modes"]:
            _mark_execution(ctx, "abac_retriever", *_retrieval_execution_summary(ctx))
        _record_retrieval_stage(ctx, "retrieved", ctx["retrieved_hits"])
        log_retrieval_summary(ctx, stage="retrieved")
        return ctx

    def reranker(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        ctx.pop("evidence_sufficiency", None)
        plan = ctx.get("route_plan")
        if plan is not None and not plan.use_reranker:
            _record_retrieval_stage(ctx, "rerank_input", [], status="skipped")
            _record_retrieval_stage(ctx, "reranked", ctx["retrieved_hits"])
            _record_retrieval_stage(ctx, "post_policy", ctx["retrieved_hits"])
            log_retrieval_summary(
                ctx, stage="rerank_skipped", before_count=len(ctx["retrieved_hits"])
            )
            return ctx
        query = plan.resolved_query if plan is not None else ctx["request"].query
        original_hits = ctx["retrieved_hits"]
        exhaustive = bool(
            plan is not None
            and plan.coverage == "exhaustive"
            and any(
                str(hit.payload.get("exhaustive_scope_origin", ""))
                == "document_class_scope"
                for hit in original_hits
            )
        )
        candidate_limit = _reranker_candidate_limit(
            plan,
            self.config.rag_reranker_max_candidates,
            source_decision=ctx.get("source_decision"),
        )
        reranker_deadline = (
            ctx.get("exhaustive_deadline")
            if exhaustive
            else monotonic()
            + float(getattr(self.config, "rag_reranker_timeout_seconds", 30.0))
        )
        rerank_result = rerank_hits_with_result(
            query,
            original_hits,
            top_k=plan.top_k if plan else self.config.rag_top_k,
            max_candidates=candidate_limit,
            model_name=self.reranker_model,
            cache_dir=self.config.rag_reranker_cache_dir,
            device=getattr(self.config, "rag_reranker_device", "auto"),
            exhaustive=exhaustive,
            deadline=reranker_deadline,
            cancellation_token=cancellation_token_from_context(ctx),
        )
        ctx["reranker_candidate_limit"] = candidate_limit
        ctx["reranker_candidate_count"] = len(rerank_result.candidates)
        ctx["reranker_input_characters"] = rerank_result.input_character_count
        ctx["reranker_passage_max_characters"] = rerank_result.passage_max_chars
        ctx["reranker_batch_count"] = rerank_result.candidate_wave_count
        ctx["reranker_stop_reason"] = rerank_result.stop_reason
        _record_retrieval_stage(ctx, "rerank_input", rerank_result.candidates)
        ranked_hits = list(rerank_result.ranked_hits)
        _record_retrieval_stage(ctx, "reranked", ranked_hits)
        if exhaustive:
            coverage_reasons = [
                reason
                for reason in (
                    rerank_result.stop_reason,
                    rerank_result.evidence_stop_reason,
                )
                if reason
            ]
            ctx["exhaustive_coverage"] = {
                "candidate_status": rerank_result.candidate_coverage_status,
                "evidence_status": rerank_result.evidence_coverage_status,
                "reasons": list(dict.fromkeys(coverage_reasons)),
                "required_obligations": list(
                    rerank_result.required_coverage_obligations
                ),
                "covered_obligations": list(rerank_result.covered_coverage_obligations),
            }
        exhaustive_incomplete = bool(
            exhaustive
            and (
                rerank_result.candidate_coverage_status != "complete"
                or rerank_result.evidence_coverage_status != "complete"
            )
        )
        if exhaustive_incomplete:
            ctx["degraded"] = True
            ctx["degraded_reason"] = ctx["degraded_reason"] or (
                "exhaustive_reranker_unavailable"
                if rerank_result.candidate_coverage_status == "unknown"
                else (
                    "exhaustive_candidate_coverage_partial"
                    if rerank_result.candidate_coverage_status != "complete"
                    else "exhaustive_final_evidence_coverage_partial"
                )
            )
            _mark_execution(
                ctx,
                "reranker",
                "fallback",
                rerank_result.stop_reason or rerank_result.evidence_stop_reason,
            )
        elif exhaustive:
            _mark_execution(
                ctx,
                "reranker",
                "deterministic",
                f"strategy={rerank_result.strategy},representatives={rerank_result.representative_scored_count}",
            )
        else:
            fallback = bool(
                ranked_hits
                and all(
                    hit.payload.get("_rerank_status") == "fallback"
                    for hit in ranked_hits
                )
            )
            detail = (
                f"candidates={len(rerank_result.candidates)},"
                f"limit={candidate_limit},"
                f"input_chars={rerank_result.input_character_count},"
                f"passage_chars={rerank_result.passage_max_chars},"
                f"batches={rerank_result.candidate_wave_count}"
            )
            if rerank_result.stop_reason is not None:
                detail = f"{detail},stop={rerank_result.stop_reason}"
            _mark_execution(
                ctx,
                "reranker",
                "fallback"
                if fallback or rerank_result.stop_reason is not None
                else "deterministic",
                detail,
            )
        if plan is not None:
            ranked_hits = _preserve_capability_coverage(
                list(rerank_result.ranked_candidates) or ranked_hits,
                ranked_hits,
                plan=plan,
            )
        ctx["retrieved_hits"] = _merge_abbreviation_glossary_hits(ctx, ranked_hits)
        _record_retrieval_stage(ctx, "post_policy", ctx["retrieved_hits"])
        log_retrieval_summary(ctx, stage="reranked", before_count=len(original_hits))
        return ctx

    def verifier(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        plan = ctx.get("route_plan")
        active_query = (
            ctx["query_rewritten"][-1]
            if ctx["query_rewritten"]
            else (plan.resolved_query if plan else ctx["request"].query)
        )
        quality = assess_evidence_quality(
            active_query, ctx["retrieved_hits"], route_plan=plan
        )
        ctx["evidence_quality"] = quality
        if ctx["retrieved_hits"]:
            ctx["verifier_decision"] = "pass"
            _mark_execution(ctx, "verifier", "deterministic", ",".join(quality.reasons))
            log_verifier_decision(ctx)
            return ctx
        retry_available = not _retrieval_retry_limit_reached(
            ctx,
            max_retries=int(
                getattr(
                    getattr(self, "config", None),
                    "rag_retrieval_max_retries",
                    1,
                )
            ),
        )
        if retry_available and _expand_auto_source_route(
            ctx,
            quality,
            live_sql_enabled=bool(
                getattr(
                    getattr(self, "config", None),
                    "connector_live_sql_enabled",
                    True,
                )
            ),
        ):
            return ctx
        if _explicit_database_route_exhausted(ctx):
            ctx["verifier_decision"] = "degrade"
            ctx["degraded"] = True
            ctx["degraded_reason"] = (
                ctx["degraded_reason"] or "explicit_source_no_answer"
            )
            _mark_execution(
                ctx, "verifier", "deterministic", "explicit_database_source_exhausted"
            )
            log_verifier_decision(ctx)
            return ctx
        return self._retry_or_degrade_retrieval(ctx, quality)

    def evidence_gate(self, ctx: QueryContext) -> QueryContext:
        """Semantically verify that final evidence can answer the resolved query."""
        _raise_if_cancelled(ctx)
        if self.evidence_gate_policy == "never":
            _mark_execution(ctx, "evidence_gate", "skipped", "policy_disabled")
            return ctx
        plan = ctx.get("route_plan")
        resolved_query = (
            plan.resolved_query if plan is not None else ctx["request"].query
        )
        structural_coverage = _structural_coverage(ctx)
        quality = ctx.get("evidence_quality")
        if quality is None:
            quality = assess_evidence_quality(
                resolved_query,
                ctx["retrieved_hits"],
                route_plan=plan,
            )
            ctx["evidence_quality"] = quality
        result = None
        if self.evidence_gate_policy == "adaptive":
            result = screen_evidence_sufficiency(
                ctx["retrieved_hits"],
                quality=quality,
                route_plan=plan,
                structural_coverage=structural_coverage,
            )
        if result is None:
            result = evaluate_evidence_sufficiency(
                resolved_query,
                ctx["retrieved_hits"],
                inference=self.ollama,
                model=self.reasoning_model,
                structural_coverage=structural_coverage,
                cancellation_token=cancellation_token_from_context(ctx),
            )
        ctx["evidence_sufficiency"] = result
        detail = (
            f"relevance={result.relevance},sufficiency={result.sufficiency},"
            f"action={result.action},missing={len(result.missing_aspects)}"
        )
        _mark_execution(
            ctx,
            "evidence_gate",
            (
                "ai_assisted"
                if result.evaluator_status == "checked"
                else "deterministic"
                if result.evaluator_status == "not_needed"
                else "fallback"
            ),
            detail,
        )

        if result.sufficiency == "sufficient" and result.action == "answer":
            ctx["verifier_decision"] = "pass"
            return ctx

        retry_available = not _retrieval_retry_limit_reached(
            ctx,
            max_retries=self.config.rag_retrieval_max_retries,
        )
        if retry_available:
            if _expand_auto_source_route(
                ctx,
                quality,
                live_sql_enabled=bool(
                    getattr(self.config, "connector_live_sql_enabled", True)
                ),
            ):
                return ctx
        if result.evaluator_status == "unavailable":
            return _finish_evidence_gate(
                ctx,
                result,
                reason="evidence_sufficiency_unavailable",
                retain_supported_hits=True,
            )
        if retry_available and result.action == "general_search" and plan is not None:
            if set(plan.capabilities) != {"general_search"}:
                return _retry_with_general_search(
                    ctx,
                    result,
                    base_top_k=self.config.rag_top_k,
                )
        if retry_available and result.action in {
            "rewrite",
            "general_search",
            "expand_source",
        }:
            return self._retry_or_degrade_retrieval(ctx, quality)

        retain_supported = bool(result.supported_aspects) and result.action == "partial"
        return _finish_evidence_gate(
            ctx,
            result,
            reason=(
                "partial_evidence"
                if retain_supported
                else "insufficient_semantic_evidence"
            ),
            retain_supported_hits=retain_supported,
        )

    def _retry_or_degrade_retrieval(self, ctx: QueryContext, quality) -> QueryContext:
        detail = ",".join(quality.reasons)
        if _retrieval_retry_limit_reached(
            ctx,
            max_retries=self.config.rag_retrieval_max_retries,
        ):
            ctx["verifier_decision"] = "degrade"
            ctx["degraded"] = True
            ctx["degraded_reason"] = (
                "Insufficient relevant evidence after retrieval retries"
            )
            ctx["retrieved_hits"] = []
            _mark_execution(ctx, "verifier", "deterministic", detail)
            log_verifier_decision(ctx)
            return ctx
        plan = ctx.get("route_plan")
        base_query = plan.resolved_query if plan is not None else ctx["request"].query
        fallback = rewrite_for_retry(base_query, ctx["retry_count"])
        rewrite_mode = "deterministic"
        rewrite_detail = None
        rewritten = fallback
        if self.config.rag_query_rewrite_llm_enabled:
            rewrite = rewrite_query_with_reasoning(
                ollama=self.ollama,
                model=self.reasoning_model,
                query=base_query,
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
                hit
                for hit in ctx["retrieved_hits"]
                if hit.payload.get("is_current", True) is True
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
                _mark_execution(
                    ctx,
                    "contradiction_detector",
                    "deterministic",
                    "hybrid_source_disagreement",
                )
        return ctx

    def evidence_builder(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        plan = ctx.get("route_plan")
        exhaustive_coverage = ctx.get("exhaustive_coverage")
        required_coverage_obligations = (
            set(exhaustive_coverage["required_obligations"])
            if exhaustive_coverage is not None
            else _coverage_obligations(ctx["retrieved_hits"])
        )
        evidence_limit, evidence_token_limit = _final_evidence_budget(
            plan,
            configured_limit=plan.top_k if plan else self.config.rag_top_k,
            configured_token_budget=ctx["token_budget"],
        )
        query_count = len(ctx.get("sub_queries") or [])
        required_query_slots = set(range(query_count)) if query_count > 1 else set()
        ctx["retrieved_hits"] = _final_evidence_hits(
            ctx,
            ctx["retrieved_hits"],
            plan=plan,
            limit=evidence_limit,
            token_budget=evidence_token_limit,
        )
        covered_query_slots = {
            slot
            for hit in ctx["retrieved_hits"]
            for slot in retrieval_query_slots(hit)
        }
        ctx["synthesis_source_limit"] = evidence_limit
        ctx["synthesis_token_limit"] = evidence_token_limit
        ctx["required_query_slot_count"] = len(required_query_slots)
        ctx["covered_query_slot_count"] = len(
            required_query_slots & covered_query_slots
        )
        final_coverage_obligations = _coverage_obligations(ctx["retrieved_hits"])
        if exhaustive_coverage is not None:
            exhaustive_coverage["covered_obligations"] = sorted(
                final_coverage_obligations
            )
        if not required_coverage_obligations <= final_coverage_obligations:
            if exhaustive_coverage is not None:
                exhaustive_coverage["evidence_status"] = "partial"
                if (
                    "final_evidence_budget_incomplete"
                    not in exhaustive_coverage["reasons"]
                ):
                    exhaustive_coverage["reasons"].append(
                        "final_evidence_budget_incomplete"
                    )
            ctx["degraded"] = True
            ctx["degraded_reason"] = (
                ctx["degraded_reason"] or "exhaustive_final_evidence_coverage_partial"
            )
        _record_retrieval_stage(ctx, "final_evidence", ctx["retrieved_hits"])
        return ctx


def _expand_auto_source_route(
    ctx: QueryContext,
    quality: EvidenceQuality,
    *,
    live_sql_enabled: bool = True,
) -> bool:
    decision = ctx.get("source_decision")
    resolved_mode = str(getattr(decision, "resolved_mode", "") or "")
    if bool(getattr(decision, "explicit", True)) or resolved_mode not in {
        "corpus_first",
        "db_first",
    }:
        return False
    if resolved_mode == "corpus_first" and (
        not live_sql_enabled
        or bool(ctx["request"].document_ids)
        or not _route_plans_live_sql(ctx)
    ):
        return False
    ctx["source_primary_hits"] = list(ctx["retrieved_hits"])
    ctx["source_expansion_from"] = resolved_mode
    ctx["source_decision"] = replace(
        decision,
        resolved_mode="hybrid",
        reason=f"{getattr(decision, 'reason', 'auto')}:evidence_expansion",
    )
    ctx["retrieved_hits"] = []
    ctx["retry_count"] += 1
    ctx["verifier_decision"] = "retry"
    detail = ",".join(quality.reasons)
    _mark_execution(
        ctx,
        "verifier",
        "deterministic",
        f"source_expansion={resolved_mode}->hybrid,{detail}",
    )
    log_verifier_decision(ctx)
    return True


def _route_plans_live_sql(ctx: QueryContext) -> bool:
    plan = ctx.get("route_plan")
    return plan is not None and "live_sql" in plan.capabilities


def _explicit_database_route_exhausted(ctx: QueryContext) -> bool:
    decision = ctx.get("source_decision")
    return (
        bool(getattr(decision, "explicit", False))
        and str(getattr(decision, "resolved_mode", "") or "") == "db_only"
    )


def _retry_with_general_search(
    ctx: QueryContext,
    result: EvidenceSufficiencyResult,
    *,
    base_top_k: int,
) -> QueryContext:
    plan = ctx.get("route_plan")
    if plan is None:
        raise RuntimeError("general-search correction requires a route plan")
    settings = retrieval_settings_for(
        ("general_search",),
        response_mode=plan.response_mode,
        scope=plan.scope,
        coverage="focused",
        temporal_scope=plan.temporal_scope,
        query=plan.resolved_query,
        base_top_k=base_top_k,
    )
    corrected = replace(
        plan,
        capabilities=("general_search",),
        coverage="focused",
        sub_queries=(),
        planner_reason=f"{plan.planner_reason}; semantic evidence correction",
        intent="general_rag",
        secondary_intents=(),
        public_intent="factual_simple",
        debug_reason=f"{plan.debug_reason}; semantic evidence correction",
        **settings,
    )
    _apply_route_plan(ctx, corrected)
    ctx["retrieved_hits"] = []
    ctx["retry_count"] += 1
    ctx["verifier_decision"] = "retry"
    _mark_execution(
        ctx,
        "evidence_gate",
        "ai_assisted",
        f"action=general_search,missing={len(result.missing_aspects)}",
    )
    return ctx


def _finish_evidence_gate(
    ctx: QueryContext,
    result: EvidenceSufficiencyResult,
    *,
    reason: str,
    retain_supported_hits: bool,
) -> QueryContext:
    ctx["verifier_decision"] = "degrade"
    ctx["degraded"] = True
    ctx["degraded_reason"] = ctx["degraded_reason"] or reason
    if not retain_supported_hits:
        ctx["retrieved_hits"] = []
    _mark_execution(
        ctx,
        "evidence_gate",
        "fallback" if result.evaluator_status == "unavailable" else "ai_assisted",
        (
            f"relevance={result.relevance},sufficiency={result.sufficiency},"
            f"action={result.action},missing={len(result.missing_aspects)}"
        ),
    )
    return ctx


def _structural_coverage(ctx: QueryContext) -> StructuralCoverage:
    plan = ctx.get("route_plan")
    if plan is None or plan.coverage != "exhaustive":
        return "not_applicable"
    coverage = ctx.get("exhaustive_coverage")
    if coverage is None:
        return "unknown"
    statuses = {
        str(coverage.get("candidate_status") or "unknown"),
        str(coverage.get("evidence_status") or "unknown"),
    }
    if statuses == {"complete"}:
        return "complete"
    if "unknown" in statuses:
        return "unknown"
    return "partial"


def _merge_capability_hits(
    primary: list[SearchHit],
    secondary: list[SearchHit],
    *,
    capabilities: tuple[RetrievalCapability, ...],
) -> list[SearchHit]:
    """Interleave capability results and retain their lineage through deduplication."""
    requested = set(capabilities)
    merged: list[SearchHit] = []
    for left, right in zip_longest(primary, secondary):
        if left is not None:
            origins: list[RetrievalCapability] = []
            live_sql_hit = (
                left.payload.get("source_type") == "connector_live_sql_database_scope"
            )
            if live_sql_hit:
                origins.append("live_sql")
            elif "general_search" in requested:
                origins.append("general_search")
            if (
                not live_sql_hit
                and "structured_query" in requested
                and _has_structured_evidence(left)
            ):
                origins.append("structured_query")
            if (
                "document_search" in requested
                and left.payload.get("exhaustive_scope_origin")
                == "document_class_scope"
            ):
                origins.append("document_search")
            merged.append(_with_capability_origins(left, origins))
        if right is not None:
            origins = ["global_graph"] if "global_graph" in requested else []
            merged.append(_with_capability_origins(right, origins))

    origins_by_key: dict[str, set[RetrievalCapability]] = {}
    for hit in merged:
        for key in _dedupe_keys(hit):
            origins_by_key.setdefault(key, set()).update(_capability_origins(hit))
    return [
        _with_capability_origins(
            hit,
            {
                origin
                for key in _dedupe_keys(hit)
                for origin in origins_by_key.get(key, ())
            },
        )
        for hit in dedupe_hits(merged)
    ]


def _preserve_capability_coverage(
    ranked_candidates: list[SearchHit],
    ranked: list[SearchHit],
    *,
    plan: RoutePlan,
) -> list[SearchHit]:
    """Keep one scored result per requested retrieval capability within top_k."""
    limit = plan.top_k
    reserves: list[SearchHit] = []
    covered = {
        capability for hit in ranked[:limit] for capability in _capability_origins(hit)
    }
    if (
        len(set(plan.capabilities)) > 1
        and "general_search" in plan.capabilities
        and not any(
            _capability_origins(hit) == ("general_search",) for hit in ranked[:limit]
        )
    ):
        covered.discard("general_search")
    for capability in plan.capabilities:
        if capability in covered:
            continue
        matching = [
            hit
            for hit in ranked_candidates
            if capability in _capability_origins(hit)
        ]
        if not matching:
            continue
        if capability == "general_search":
            general_only = [
                hit
                for hit in matching
                if _capability_origins(hit) == ("general_search",)
            ]
            matching = general_only or matching
        reserves.append(matching[0])

    reserves = dedupe_hits(reserves)
    return dedupe_hits([*ranked[:1], *reserves, *ranked[1:]])[:limit]


def _with_capability_origins(
    hit: SearchHit,
    origins: list[RetrievalCapability] | set[RetrievalCapability],
) -> SearchHit:
    combined = tuple(dict.fromkeys((*_capability_origins(hit), *origins)))
    if not combined:
        return hit
    return SearchHit(
        point_id=hit.point_id,
        score=hit.score,
        payload={**hit.payload, "_retrieval_capabilities": list(combined)},
    )


def _capability_origins(hit: SearchHit) -> tuple[RetrievalCapability, ...]:
    raw = hit.payload.get("_retrieval_capabilities")
    if not isinstance(raw, list | tuple):
        return ()
    allowed = {
        "general_search",
        "structured_query",
        "live_sql",
        "document_search",
        "global_graph",
        "document_navigation",
        "decomposed_search",
    }
    return tuple(
        dict.fromkeys(origin for value in raw if (origin := str(value)) in allowed)
    )  # type: ignore[return-value]


def _merge_abbreviation_glossary_hits(
    ctx: QueryContext,
    hits: list[SearchHit],
) -> list[SearchHit]:
    supporting_hits = ctx.get("abbreviation_glossary_hits")
    corpus_hits = [
        hit
        for hit in hits
        if hit.payload.get("doc_type") != ABBREVIATION_GLOSSARY_DOC_TYPE
    ]
    return (
        dedupe_hits([*corpus_hits, *supporting_hits])
        if supporting_hits is not None
        else corpus_hits
    )


def _final_evidence_hits(
    ctx: QueryContext,
    hits: list[SearchHit],
    *,
    plan: RoutePlan | None,
    limit: int,
    token_budget: int,
) -> list[SearchHit]:
    return build_evidence_hits(
        _merge_abbreviation_glossary_hits(ctx, hits),
        token_budget=token_budget,
        limit=limit,
        broader_table_context=(
            _should_promote_parent_context(plan)
            or any(
                hit.payload.get("coverage_role") == "exhaustive_section_representative"
                for hit in hits
            )
        ),
        query=" ".join(ctx.get("sub_queries") or [ctx["request"].query]),
    )


def _record_retrieval_stage(
    ctx: QueryContext,
    name: RetrievalStageName,
    hits: list[SearchHit] | tuple[SearchHit, ...],
    *,
    status: RetrievalStageStatus = "completed",
) -> None:
    stages = ctx.get("retrieval_trace")
    if stages is None:
        return
    if name == "retrieved":
        attempt = sum(stage.name == "retrieved" for stage in stages)
    else:
        attempt = next(
            (stage.attempt for stage in reversed(stages) if stage.name == "retrieved"),
            0,
        )
    stages.append(retrieval_trace_stage(name, hits, attempt=attempt, status=status))
