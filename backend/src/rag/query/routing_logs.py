"""Structured route decision logging."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Any

from .state import QueryContext
from .qdrant import SearchHit
from .routing_models import RoutePlan

logger = logging.getLogger("rag.query.routing")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False


def log_query_start(ctx: QueryContext, *, stream: bool) -> None:
    artifact_request = ctx.get("artifact_request")
    payload = {
        **_context_fields(ctx),
        "event": "rag.query_start",
        "stream": stream,
        "query_hash": _query_hash(ctx["request"].query),
        "query_length": len(ctx["request"].query),
        "selected_group_path": ctx["request"].group_path,
        "document_scope_count": len(ctx["request"].document_ids),
        "visible_group_count": len(ctx["user"].group_paths),
        "has_artifact_request": "artifact_request" in ctx,
        "artifact_formats": list(artifact_request.formats) if artifact_request is not None else [],
        "artifact_needs_clarification": artifact_request.needs_clarification if artifact_request is not None else False,
        "artifact_objective_hash": _query_hash(artifact_request.content_query) if artifact_request is not None else None,
    }
    _log_info(payload)


def log_artifact_plan(ctx: QueryContext) -> None:
    plan = ctx.get("artifact_plan")
    if plan is None:
        return
    _log_info({
        **_context_fields(ctx),
        "event": "rag.artifact_plan",
        "artifact_type": plan.artifact_type,
        "formats": list(plan.formats),
        "operations": list(plan.operations),
        "task_count": len(plan.tasks),
        "tasks": [
            {
                "operation": task.operation,
                "retrieval_strategy": task.retrieval_strategy,
                "coverage_requirement": task.coverage_requirement,
                "target_section": task.target_section,
            }
            for task in plan.tasks
        ],
    })


def log_artifact_evidence(ctx: QueryContext) -> None:
    coverage = ctx.get("artifact_coverage")
    units = ctx.get("artifact_evidence", ())
    if coverage is None:
        return
    _log_info({
        **_context_fields(ctx),
        "event": "rag.artifact_evidence",
        "coverage_status": coverage.status,
        "evidence_count": coverage.evidence_count,
        "relevant_evidence_count": coverage.relevant_evidence_count,
        "documents_searched": coverage.documents_searched,
        "documents_expected": coverage.documents_expected,
        "retrieval_iterations": coverage.retrieval_iterations,
        "warnings": list(coverage.warnings),
        "content_types": _count_values(unit.content_type for unit in units),
    })


def log_artifact_composition(ctx: QueryContext) -> None:
    content = ctx.get("artifact_content")
    plan = ctx.get("artifact_plan")
    if content is None or plan is None:
        return
    _log_info({
        **_context_fields(ctx),
        "event": "rag.artifact_composition",
        "mode": ctx["execution_modes"].get("artifact_composer"),
        "artifact_type": plan.artifact_type,
        "operations": list(plan.operations),
        "section_count": len(content.sections),
        "claim_count": len(content.claims),
        "table_count": sum(len(section.tables) for section in content.sections),
        "table_row_count": sum(len(table.rows) for section in content.sections for table in section.tables),
        "citation_count": len(content.citations),
    })


def log_artifact_validation(ctx: QueryContext) -> None:
    validation = ctx.get("artifact_validation")
    if validation is None:
        return
    _log_info({
        **_context_fields(ctx),
        "event": "rag.artifact_validation",
        "passed": validation.passed,
        "support_score": _round(validation.support_score),
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
    })


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
        "secondary_intents": list(plan.secondary_intents),
        "confidence": round(plan.confidence, 3),
        "margin": round(plan.margin, 3),
        "route_method": plan.route_method,
        "risk_level": plan.risk_level,
        "retrieval_strategy": plan.retrieval_strategy,
        "search_mode": plan.search_mode,
        "chunk_granularity": plan.chunk_granularity,
        "top_k": plan.top_k,
        "filters": plan.filters,
        "rule_hits": [
            {"intent": hit.intent, "signal": hit.signal, "weight": hit.weight, "strength": hit.strength}
            for hit in plan.rule_hits
        ],
        "penalties": [
            {"intent": penalty.intent, "reason": penalty.reason, "weight": penalty.weight}
            for penalty in plan.penalties
        ],
    }
    _log_info(payload)


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


def log_artifact_result(
    ctx: QueryContext,
    *,
    requested: bool,
    skipped_reason: str | None = None,
    artifact_count: int = 0,
    failure_count: int = 0,
    formats: Iterable[str] = (),
    failure_details: Iterable[dict[str, str]] = (),
) -> None:
    payload = {
        **_context_fields(ctx),
        "event": "rag.artifact_result",
        "requested": requested,
        "skipped_reason": skipped_reason,
        "artifact_count": artifact_count,
        "failure_count": failure_count,
        "formats": list(formats),
        "failure_details": list(failure_details),
    }
    _log_info(payload)


def log_node_timing(ctx: QueryContext, *, node: str, duration_ms: int) -> None:
    payload = {
        **_context_fields(ctx),
        "event": "rag.node_timing",
        "node": node,
        "duration_ms": max(0, int(duration_ms)),
        "execution_mode": ctx["execution_modes"].get(node),
        "detail": ctx["execution_details"].get(node),
    }
    _log_info(payload)


def log_query_complete(ctx: QueryContext, *, stream: bool) -> None:
    response = ctx.get("response")
    payload = {
        **_context_fields(ctx),
        "event": "rag.query_complete",
        "stream": stream,
        "latency_ms": response.latency_ms if response is not None else None,
        "intent": response.intent if response is not None else ctx["intent"],
        "source_count": len(response.sources) if response is not None else 0,
        "artifact_count": len(response.artifacts) if response is not None else 0,
        "faithfulness_score": _round(response.faithfulness_score) if response is not None else None,
        "faithfulness_status": response.faithfulness_status if response is not None else ctx["faithfulness_status"],
        "degraded": response.degraded if response is not None else ctx["degraded"],
        "degraded_reason": response.degraded_reason if response is not None else ctx["degraded_reason"],
        "conflict_flag": response.conflict_flag if response is not None else ctx["conflict_flag"],
        "retry_count": ctx["retry_count"],
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
    payload = {
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
        "confidence": round(plan.confidence, 3),
        "margin": round(plan.margin, 3),
        "route_method": plan.route_method,
        "retrieval_strategy": plan.retrieval_strategy,
        "search_mode": plan.search_mode,
        "chunk_granularity": plan.chunk_granularity,
        "top_k": plan.top_k,
        "filters": plan.filters,
        "retrieved_hit_count": len(ctx["retrieved_hits"]),
        "evidence_source_count": len(response.sources),
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
            "rerank_status": payload.get("_rerank_status"),
            "rerank_error": payload.get("_rerank_error"),
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


def _slowest_nodes(node_timings: list[dict[str, str | int | None]], *, limit: int = 5) -> list[dict[str, str | int | None]]:
    return sorted(node_timings, key=lambda item: int(item.get("duration_ms") or 0), reverse=True)[:limit]


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _round(value: object, digits: int = 3) -> float | None:
    if not isinstance(value, int | float):
        return None
    return round(float(value), digits)


def _log_info(payload: dict[str, Any]) -> None:
    logger.info(json.dumps(payload, sort_keys=True))
