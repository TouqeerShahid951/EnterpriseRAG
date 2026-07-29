"""Structured route decision logging."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from rag.query.state import QueryContext
from rag.query.qdrant import SearchHit
from rag.query.routing.routing_models import RoutePlan

logger = logging.getLogger("rag.query.routing")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False


def log_query_start(ctx: QueryContext, *, stream: bool) -> None:
    payload = {
        **_context_fields(ctx),
        "event": "rag.query_start",
        "stream": stream,
        "query_hash": _query_hash(ctx["request"].query),
        "query_length": len(ctx["request"].query),
        "requested_source_mode": ctx["request"].source_mode,
        "selected_group_path": ctx["request"].group_path,
        "document_scope_count": len(ctx["request"].document_ids),
        "visible_group_count": len(ctx["user"].group_paths),
    }
    _log_info(payload)


def log_route_decision(*, trace_id: str, session_id: str, user_id: str, permission_version: int, plan: RoutePlan) -> None:
    payload = {
        "event": "rag.route_decision",
        "trace_id": trace_id,
        "session_id": session_id,
        "user_id": user_id,
        "permission_version": permission_version,
        "query_hash": _query_hash(plan.original_query),
        "query_length": len(plan.original_query),
        "intent": plan.intent,
        "public_intent": plan.public_intent,
        "capabilities": list(plan.capabilities),
        "response_mode": plan.response_mode,
        "scope": plan.scope,
        "coverage": plan.coverage,
        "temporal_scope": plan.temporal_scope,
        "sub_query_count": len(plan.sub_queries),
        "route_method": plan.route_method,
        "risk_level": plan.risk_level,
        "retrieval_strategy": plan.retrieval_strategy,
        "search_mode": plan.search_mode,
        "chunk_granularity": plan.chunk_granularity,
        "top_k": plan.top_k,
        "filters": plan.filters,
        "penalties": [
            {"intent": penalty.intent, "reason": penalty.reason, "weight": penalty.weight}
            for penalty in plan.penalties
        ],
    }
    _log_info(payload)


def log_conversation_resolution(ctx: QueryContext) -> None:
    resolution = ctx.get("conversation_resolution")
    if resolution is None:
        return
    _log_info(
        {
            **_context_fields(ctx),
            "event": "rag.conversation_resolution",
            "relation": resolution.relation,
            "method": resolution.method,
            "context_turn_count": resolution.context_turn_count,
            "antecedent_turn_ids": list(resolution.antecedent_turn_ids),
            "clarification": resolution.relation == "ambiguous",
            "effective_query_hash": _query_hash(resolution.effective_query),
            "effective_query_length": len(resolution.effective_query),
        }
    )


def log_retrieval_summary(ctx: QueryContext, *, stage: str, before_count: int | None = None) -> None:
    hits = ctx["retrieved_hits"]
    payload = {
        **_context_fields(ctx),
        "event": "rag.retrieval_summary",
        "stage": stage,
        "hit_count": len(hits),
        "before_count": before_count,
        "top_hits": _top_hit_summaries(hits),
        "distinct_doc_count": len(_doc_ids(hits)),
        "max_retrieval_score": _round(max((hit.score for hit in hits), default=0.0)),
        "max_rerank_score": _round(max(_rerank_scores(hits), default=0.0)) if _rerank_scores(hits) else None,
    }
    _log_info(payload)


def log_verifier_decision(ctx: QueryContext) -> None:
    quality = ctx.get("evidence_quality")
    payload = {
        **_context_fields(ctx),
        **_source_routing_fields(ctx),
        "event": "rag.verifier_decision",
        "decision": ctx["verifier_decision"],
        "retry_count": ctx["retry_count"],
        "degraded": ctx["degraded"],
        "degraded_reason": ctx["degraded_reason"],
        "retrieved_hit_count": len(ctx["retrieved_hits"]),
        "evidence_quality": quality.quality if quality is not None else None,
        "evidence_quality_reasons": list(quality.reasons) if quality is not None else [],
        "evidence_score": _round(quality.evidence_score) if quality is not None else None,
        "evidence_outcome": quality.outcome if quality is not None else None,
        "query_token_coverage": _round(quality.query_token_coverage) if quality is not None else None,
        "max_retrieval_score": _round(quality.max_retrieval_score) if quality is not None else None,
        "max_rerank_score": _round(quality.max_rerank_score) if quality is not None and quality.max_rerank_score is not None else None,
        "distinct_doc_count": quality.distinct_doc_count if quality is not None else 0,
        "structured_hit_count": quality.structured_hit_count if quality is not None else 0,
        "metadata_hit_count": quality.metadata_hit_count if quality is not None else 0,
        "document_class_match_count": quality.document_class_match_count if quality is not None else 0,
        "execution_mode": ctx["execution_modes"].get("verifier"),
        "detail": ctx["execution_details"].get("verifier"),
    }
    _log_info(payload)


def log_faithfulness_result(ctx: QueryContext, *, failed: bool) -> None:
    payload = {
        **_context_fields(ctx),
        "event": "rag.faithfulness_result",
        "score": _round(ctx["faithfulness_score"]),
        "status": ctx["faithfulness_status"],
        "failed": failed,
        "unfounded_claim_count": len(ctx["unfounded_claims"]),
        "degraded": ctx["degraded"],
        "degraded_reason": ctx["degraded_reason"],
    }
    _log_info(payload)


def log_node_timing(ctx: QueryContext, *, node: str, duration_ms: int) -> None:
    recorded = next(
        (
            timing
            for timing in reversed(ctx["node_timings"])
            if timing.get("node") == node
        ),
        {},
    )
    payload = {
        **_context_fields(ctx),
        **_runtime_budget_fields(ctx),
        "event": "rag.node_timing",
        "node": node,
        "duration_ms": max(0, int(duration_ms)),
        "execution_mode": ctx["execution_modes"].get(node),
        "detail": ctx["execution_details"].get(node),
        "phase_timings_ms": recorded.get("phase_timings_ms", {}),
    }
    _log_info(payload)


def log_query_complete(ctx: QueryContext, *, stream: bool) -> None:
    response = ctx.get("response")
    sufficiency = ctx.get("evidence_sufficiency")
    payload = {
        **_context_fields(ctx),
        **_source_routing_fields(ctx),
        **_runtime_budget_fields(ctx),
        "event": "rag.query_complete",
        "stream": stream,
        "latency_ms": response.latency_ms if response is not None else None,
        "intent": response.intent if response is not None else ctx["intent"],
        "source_count": len(response.sources) if response is not None else 0,
        "artifact_count": len(response.artifacts) if response is not None else 0,
        "answer_status": response.answer_status if response is not None else None,
        "faithfulness_score": _round(response.faithfulness_score) if response is not None else None,
        "faithfulness_status": response.faithfulness_status if response is not None else ctx["faithfulness_status"],
        "degraded": response.degraded if response is not None else ctx["degraded"],
        "degraded_reason": response.degraded_reason if response is not None else ctx["degraded_reason"],
        "conflict_flag": response.conflict_flag if response is not None else ctx["conflict_flag"],
        "retry_count": ctx["retry_count"],
        "evidence_relevance": sufficiency.relevance if sufficiency is not None else None,
        "evidence_sufficiency": sufficiency.sufficiency if sufficiency is not None else None,
        "evidence_action": sufficiency.action if sufficiency is not None else None,
        "evidence_evaluator_status": (
            sufficiency.evaluator_status if sufficiency is not None else None
        ),
        "route_reroute_count": ctx["route_reroute_count"],
        "node_timings": ctx["node_timings"],
        "slowest_nodes": _slowest_nodes(ctx["node_timings"]),
    }
    _log_info(payload)


def log_query_error(ctx: QueryContext, *, stream: bool, exc: BaseException) -> None:
    payload = {
        **_context_fields(ctx),
        "event": "rag.query_error",
        "stream": stream,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "retry_count": ctx["retry_count"],
        "route_reroute_count": ctx["route_reroute_count"],
        "node_timings": ctx["node_timings"],
        "slowest_nodes": _slowest_nodes(ctx["node_timings"]),
    }
    logger.exception(json.dumps(payload, sort_keys=True))


def log_route_outcome(ctx: QueryContext) -> None:
    plan = ctx.get("route_plan")
    if plan is None:
        return
    response = ctx["response"]
    evidence_quality = ctx.get("evidence_quality")
    sufficiency = ctx.get("evidence_sufficiency")
    payload = {
        **_source_routing_fields(ctx),
        **_runtime_budget_fields(ctx),
        "event": "rag.route_outcome",
        "trace_id": ctx["trace_id"],
        "session_id": ctx["session_id"],
        "user_id": ctx["user"].user_id,
        "permission_version": ctx["user"].permission_version,
        "query_hash": _query_hash(ctx["request"].query),
        "initial_intent": ctx.get("initial_route_intent", plan.intent),
        "final_intent": plan.intent,
        "public_intent": plan.public_intent,
        "response_intent": response.intent,
        "capabilities": list(plan.capabilities),
        "response_mode": plan.response_mode,
        "scope": plan.scope,
        "coverage": plan.coverage,
        "temporal_scope": plan.temporal_scope,
        "sub_query_count": len(plan.sub_queries),
        "route_method": plan.route_method,
        "retrieval_strategy": plan.retrieval_strategy,
        "search_mode": plan.search_mode,
        "chunk_granularity": plan.chunk_granularity,
        "top_k": plan.top_k,
        "filters": plan.filters,
        "retrieved_hit_count": len(ctx["retrieved_hits"]),
        "evidence_source_count": len(response.sources),
        "answer_status": response.answer_status,
        "max_retrieval_score": round(max((hit.score for hit in ctx["retrieved_hits"]), default=0.0), 3),
        "max_rerank_score": (
            round(evidence_quality.max_rerank_score, 3)
            if evidence_quality is not None and evidence_quality.max_rerank_score is not None
            else None
        ),
        "evidence_quality": evidence_quality.quality if evidence_quality is not None else None,
        "evidence_quality_reasons": list(evidence_quality.reasons) if evidence_quality is not None else [],
        "evidence_score": round(evidence_quality.evidence_score, 3) if evidence_quality is not None else None,
        "evidence_outcome": evidence_quality.outcome if evidence_quality is not None else None,
        "query_token_coverage": (
            round(evidence_quality.query_token_coverage, 3) if evidence_quality is not None else None
        ),
        "distinct_doc_count": evidence_quality.distinct_doc_count if evidence_quality is not None else 0,
        "structured_hit_count": evidence_quality.structured_hit_count if evidence_quality is not None else 0,
        "metadata_hit_count": evidence_quality.metadata_hit_count if evidence_quality is not None else 0,
        "document_class_match_count": (
            evidence_quality.document_class_match_count if evidence_quality is not None else 0
        ),
        "evidence_relevance": sufficiency.relevance if sufficiency is not None else None,
        "evidence_sufficiency": sufficiency.sufficiency if sufficiency is not None else None,
        "evidence_action": sufficiency.action if sufficiency is not None else None,
        "evidence_supported_aspect_count": (
            len(sufficiency.supported_aspects) if sufficiency is not None else 0
        ),
        "evidence_missing_aspect_count": (
            len(sufficiency.missing_aspects) if sufficiency is not None else 0
        ),
        "evidence_evaluator_status": (
            sufficiency.evaluator_status if sufficiency is not None else None
        ),
        "route_reroute_count": ctx["route_reroute_count"],
        "verifier_decision": ctx["verifier_decision"],
        "conflict_checker_used": ctx["conflict_checker_used"],
        "conflict_flag": ctx["conflict_flag"],
        "degraded": ctx["degraded"],
        "degraded_reason": ctx["degraded_reason"],
        "faithfulness_score": round(ctx["faithfulness_score"], 3),
        "faithfulness_status": ctx["faithfulness_status"],
        "unfounded_claim_count": len(ctx["unfounded_claims"]),
        "synthesis_profile": ctx.get("synthesis_profile"),
    }
    _log_info(payload)


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _context_fields(ctx: QueryContext) -> dict[str, object]:
    return {
        "trace_id": ctx["trace_id"],
        "session_id": ctx["session_id"],
        "user_id": ctx["user"].user_id,
        "permission_version": ctx["user"].permission_version,
    }


def _runtime_budget_fields(ctx: QueryContext) -> dict[str, object]:
    return {
        "reranker_candidate_limit": ctx.get("reranker_candidate_limit"),
        "reranker_candidate_count": ctx.get("reranker_candidate_count"),
        "reranker_input_characters": ctx.get("reranker_input_characters"),
        "reranker_passage_max_characters": ctx.get(
            "reranker_passage_max_characters"
        ),
        "reranker_batch_count": ctx.get("reranker_batch_count"),
        "reranker_stop_reason": ctx.get("reranker_stop_reason"),
        "synthesis_source_limit": ctx.get("synthesis_source_limit"),
        "synthesis_token_limit": ctx.get("synthesis_token_limit"),
        "synthesis_context_count": ctx.get("synthesis_context_count"),
        "synthesis_estimated_prompt_tokens": ctx.get(
            "synthesis_estimated_prompt_tokens"
        ),
        "required_query_slot_count": ctx.get("required_query_slot_count"),
        "covered_query_slot_count": ctx.get("covered_query_slot_count"),
    }


def _source_routing_fields(ctx: QueryContext) -> dict[str, object]:
    decision = ctx.get("source_decision")
    if decision is None:
        return {
            "requested_source_mode": ctx["request"].source_mode,
            "resolved_source_mode": None,
        }
    reason = str(getattr(decision, "reason", "") or "")
    return {
        "requested_source_mode": getattr(decision, "requested_mode", ctx["request"].source_mode),
        "resolved_source_mode": getattr(decision, "resolved_mode", None),
        "source_routing_reason": reason,
        "source_routing_confidence": _round(getattr(decision, "routing_confidence", None)),
        "source_router_mode": getattr(decision, "router_mode", None),
        "preferred_source": getattr(decision, "preferred_source", None),
        "source_expansion_performed": ":evidence_expansion" in reason,
        "source_signal_scores": {
            "structured": getattr(decision, "structured_score", 0),
            "corpus": getattr(decision, "corpus_score", 0),
            "source_match": getattr(decision, "source_match_score", 0),
            "document_match": getattr(decision, "document_match_score", 0),
        },
        "live_sql_mode": ctx["execution_modes"].get("live_sql_retriever"),
    }


def _top_hit_summaries(hits: list[SearchHit], *, limit: int = 5) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for index, hit in enumerate(hits[:limit], 1):
        payload = hit.payload
        summaries.append({
            "rank": index,
            "point_id": hit.point_id,
            "doc_id": payload.get("doc_id"),
            "chunk_id": payload.get("chunk_id"),
            "page": payload.get("page"),
            "chunk_type": payload.get("chunk_type"),
            "retrieval_score": _round(hit.score),
            "rerank_score": _round(payload.get("_rerank_score")),
            "rerank_adjusted_score": _round(payload.get("_rerank_adjusted_score")),
            "rerank_status": payload.get("_rerank_status"),
            "rerank_error": payload.get("_rerank_error"),
            "low_value_penalty": _round(payload.get("_low_value_penalty")),
            "low_value_reasons": payload.get("_low_value_reasons"),
            "is_current": payload.get("is_current"),
            "structured_origin": payload.get("structured_origin"),
        })
    return summaries


def _doc_ids(hits: list[SearchHit]) -> set[str]:
    return {
        str(hit.payload["doc_id"])
        for hit in hits
        if hit.payload.get("doc_id") not in (None, "")
    }


def _rerank_scores(hits: list[SearchHit]) -> list[float]:
    return [
        float(score)
        for hit in hits
        if (score := hit.payload.get("_rerank_score")) is not None and isinstance(score, int | float)
    ]


def _slowest_nodes(
    node_timings: list[dict[str, object]], *, limit: int = 5
) -> list[dict[str, object]]:
    return sorted(node_timings, key=lambda item: int(item.get("duration_ms") or 0), reverse=True)[:limit]


def _round(value: object, digits: int = 3) -> float | None:
    if not isinstance(value, int | float):
        return None
    return round(float(value), digits)


def _log_info(payload: dict[str, Any]) -> None:
    logger.info(json.dumps(payload, sort_keys=True))
