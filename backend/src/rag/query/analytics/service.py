"""Query analytics lifecycle and response mapping."""

from __future__ import annotations

import logging
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from ..schemas import RAGResponse
from ..state import QueryContext
from ..retrieval.retrieval_trace import RetrievalTraceStage
from ...auth.context import UserContext
from .models import (
    AnalyticsBoundaryEvent,
    AnalyticsExecutionRecord,
    AnalyticsExecutionRepository,
    AnalyticsOrigin,
    AnalyticsOutcome,
    AnalyticsWorkKind,
)
from .lineage_metadata import candidate_metadata
from .heartbeat import execution_heartbeat

logger = logging.getLogger(__name__)


class AnalyticsRecorder:
    def __init__(
        self,
        repository: AnalyticsExecutionRepository,
        *,
        reconciliation_grace_seconds: int = 3600,
        retrieval_lineage_max_candidates: int = 500,
        retrieval_lineage_max_bytes: int = 512_000,
    ) -> None:
        if reconciliation_grace_seconds < 1:
            raise ValueError("reconciliation_grace_seconds must be positive")
        if retrieval_lineage_max_candidates < 1:
            raise ValueError("retrieval_lineage_max_candidates must be positive")
        if retrieval_lineage_max_bytes < 32_000:
            raise ValueError("retrieval_lineage_max_bytes must be at least 32000")
        self.repository = repository
        self.reconciliation_grace_seconds = reconciliation_grace_seconds
        self.retrieval_lineage_max_candidates = retrieval_lineage_max_candidates
        self.retrieval_lineage_max_bytes = retrieval_lineage_max_bytes

    def record_boundary(
        self,
        *,
        route_path: str,
        status_code: int,
        reason_code: str,
        occurred_at: datetime | None = None,
        actor_id: str | None = None,
    ) -> None:
        self._write(
            lambda: self.repository.record_boundary_event(
                AnalyticsBoundaryEvent(
                    event_id=str(uuid4()),
                    occurred_at=occurred_at or datetime.now(UTC),
                    route_path=route_path[:240],
                    status_code=status_code,
                    reason_code=reason_code[:80],
                    actor_id=actor_id,
                )
            )
        )

    def start(
        self,
        *,
        execution_id: str,
        trace_id: str,
        session_id: str,
        user: UserContext,
        request: Any,
        started_at: datetime,
        origin: AnalyticsOrigin,
        work_kind: AnalyticsWorkKind,
        cohort: dict[str, object] | None = None,
    ) -> None:
        cohort = cohort or {}
        heartbeat_at = datetime.now(UTC)
        record = AnalyticsExecutionRecord(
            execution_id=execution_id,
            trace_id=trace_id,
            session_id=session_id,
            actor_id=user.user_id,
            permission_version=user.permission_version,
            origin=origin,
            work_kind=work_kind,
            group_path=request.group_path,
            lifecycle="in_flight",
            started_at=started_at,
            reconciliation_deadline_at=heartbeat_at + timedelta(seconds=self.reconciliation_grace_seconds),
            last_heartbeat_at=heartbeat_at,
            requested_source_mode=request.source_mode,
            model_cohort=_cohort_text(cohort, "model_cohort"),
            configuration_digest=_cohort_text(cohort, "configuration_digest"),
            application_image_digest=_cohort_text(cohort, "application_image_digest"),
            cohort_snapshot=(cohort.get("snapshot") if isinstance(cohort.get("snapshot"), dict) else None),
        )
        self._write(lambda: self.repository.start_execution(record))

    def heartbeat(self, execution_id: str):
        return execution_heartbeat(self.repository, execution_id, grace_seconds=self.reconciliation_grace_seconds)

    def record_denial(
        self, *, user: UserContext, request: Any, origin: AnalyticsOrigin,
        reason_code: str, execution_id: str,
    ) -> None:
        """Record one eligible invocation rejected before the query workflow starts."""
        now = datetime.now(UTC)
        self.start(
            execution_id=execution_id, trace_id=execution_id, session_id=str(uuid4()),
            user=user, request=request, started_at=now, origin=origin, work_kind="answer",
        )
        self._write(lambda: self.repository.finish_execution(
            execution_id, finished_at=now, outcome="access_denied", reason_code=reason_code,
            degraded=False,
        ))

    def finish_response(
        self,
        *,
        execution_id: str,
        response: RAGResponse,
        ctx: QueryContext | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        self._write(lambda: self._finish_response(
            execution_id=execution_id, response=response, ctx=ctx, finished_at=finished_at,
        ))

    def _finish_response(
        self,
        *,
        execution_id: str,
        response: RAGResponse,
        ctx: QueryContext | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        outcome = _outcome_for_response(response)
        lineage_status, lineage = _retrieval_lineage(
            ctx,
            response=response,
            max_candidates=self.retrieval_lineage_max_candidates,
            max_bytes=self.retrieval_lineage_max_bytes,
        )
        self._write(
            lambda: self.repository.finish_execution(
                execution_id,
                finished_at=finished_at or datetime.now(UTC),
                outcome=outcome,
                answer_status=response.answer_status,
                degraded=response.degraded,
                degraded_reason=response.degraded_reason,
                resolved_source_mode=response.source_mode,
                initial_intent=_context_route_value(ctx, "initial_route_intent"),
                final_intent=response.intent,
                response_mode=_context_plan_value(ctx, "response_mode"),
                latency_ms=response.latency_ms,
                verification_status=response.faithfulness_status,
                verification_method=_context_execution_value(ctx, "faithfulness_checker"),
                faithfulness_score=(
                    response.faithfulness_score
                    if response.faithfulness_status == "checked"
                    else None
                ),
                retry_count=_context_int(ctx, "retry_count"),
                route_reroute_count=_context_int(ctx, "route_reroute_count"),
                retrieved_hit_count=_context_len(ctx, "retrieved_hits"),
                evidence_source_count=len(response.sources),
                cited_source_count=_cited_source_count(response),
                max_retrieval_score=_context_score(ctx, "retrieved_hits", "score"),
                max_rerank_score=_context_rerank_score(ctx),
                retrieval_lineage_status=lineage_status,
                retrieval_lineage=lineage,
            ),
        )

    def fail(
        self,
        *,
        execution_id: str,
        finished_at: datetime | None = None,
        outcome: AnalyticsOutcome = "system_error",
        ctx: QueryContext | None = None,
    ) -> None:
        self._write(lambda: self._fail(
            execution_id=execution_id, finished_at=finished_at, outcome=outcome, ctx=ctx,
        ))

    def _fail(
        self,
        *,
        execution_id: str,
        finished_at: datetime | None = None,
        outcome: AnalyticsOutcome = "system_error",
        ctx: QueryContext | None = None,
    ) -> None:
        lineage_status, lineage = _retrieval_lineage(
            ctx,
            response=None,
            max_candidates=self.retrieval_lineage_max_candidates,
            max_bytes=self.retrieval_lineage_max_bytes,
        )
        self._write(
            lambda: self.repository.finish_execution(
                execution_id,
                finished_at=finished_at or datetime.now(UTC),
                outcome=outcome,
                retrieval_lineage_status=lineage_status,
                retrieval_lineage=lineage,
            )
        )

    def _write(self, action) -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - telemetry must not change query behavior
            logger.warning("query analytics write failed (%s)", type(exc).__name__)


def _outcome_for_response(response: RAGResponse) -> AnalyticsOutcome:
    if response.artifact_job is not None:
        return "artifact_submitted"
    return response.answer_status


def _context_route_value(ctx: QueryContext | None, key: str) -> str | None:
    value = ctx.get(key) if ctx else None
    return str(value) if value is not None else None


def _context_plan_value(ctx: QueryContext | None, key: str) -> str | None:
    plan = ctx.get("route_plan") if ctx else None
    value = getattr(plan, key, None)
    return str(value) if value is not None else None


def _context_execution_value(ctx: QueryContext | None, key: str) -> str | None:
    value = ctx.get("execution_modes", {}).get(key) if ctx else None
    return str(value) if value is not None else None


def _context_int(ctx: QueryContext | None, key: str) -> int:
    value = ctx.get(key, 0) if ctx else 0
    return max(0, int(value or 0))


def _context_len(ctx: QueryContext | None, key: str) -> int | None:
    values = ctx.get(key) if ctx else None
    return len(values) if isinstance(values, list | tuple) else None


def _context_score(ctx: QueryContext | None, collection_key: str, score_key: str) -> float | None:
    values = ctx.get(collection_key) if ctx else None
    scores = [getattr(item, score_key, None) for item in values or ()]
    numeric = [float(value) for value in scores if isinstance(value, int | float)]
    return max(numeric, default=None)


def _context_rerank_score(ctx: QueryContext | None) -> float | None:
    values = ctx.get("retrieved_hits") if ctx else None
    scores = [item.payload.get("_rerank_score") for item in values or ()]
    numeric = [float(value) for value in scores if isinstance(value, int | float)]
    return max(numeric, default=None)


def _cited_source_count(response: RAGResponse) -> int | None:
    return sum(
        1
        for source in response.sources
        if source.citation_targets or source.evidence_windows
    )


def _retrieval_lineage(
    ctx: QueryContext | None,
    *,
    response: RAGResponse | None,
    max_candidates: int,
    max_bytes: int,
) -> tuple[str, dict[str, object] | None]:
    if ctx is None or "retrieval_trace" not in ctx:
        return "unavailable", None

    trace = ctx["retrieval_trace"]
    stages: list[dict[str, object]] = []
    candidate_count = 0
    serialized_candidate_count = 0
    remaining = max_candidates
    truncated = False
    for stage in trace:
        candidate_count += len(stage.candidates)
        rows = []
        for candidate in stage.candidates[:remaining]:
            row = candidate_metadata(candidate.to_row())
            row["candidate_key"] = _candidate_key(row)
            rows.append(row)
        remaining -= len(rows)
        stage_truncated = len(rows) < len(stage.candidates)
        truncated = truncated or stage_truncated
        serialized_candidate_count += len(rows)
        stages.append(
            {
                "name": stage.name,
                "attempt": stage.attempt,
                "status": stage.status,
                "candidate_count": len(stage.candidates),
                "truncated": stage_truncated,
                "candidates": rows,
            }
        )

    lineage: dict[str, object] = {
        "schema_version": 1,
        "status": "available",
        "truncated": truncated,
        "stage_count": len(stages),
        "candidate_count": candidate_count,
        "serialized_candidate_count": serialized_candidate_count,
        "stages": stages,
        "counts": {
            "candidate_chunks": candidate_count,
            "coverage_units": _coverage_unit_count(trace),
            "context_blocks": ctx.get("synthesis_context_count"),
            "citation_anchors": len(ctx.get("citation_source_keys", [])),
        },
        "coverage": {
            "required_query_slot_count": ctx.get("required_query_slot_count"),
            "covered_query_slot_count": ctx.get("covered_query_slot_count"),
            "status": (
                "available"
                if "required_query_slot_count" in ctx
                and "covered_query_slot_count" in ctx
                else "incomplete"
            ),
        },
        "generation": {
            "status": "available" if "synthesis_source_keys" in ctx else "unavailable",
            "source_count": len(ctx.get("synthesis_source_keys", [])),
            "source_keys": ctx.get("synthesis_source_keys", []),
            "context_block_count": ctx.get("synthesis_context_count"),
            "estimated_prompt_tokens": ctx.get("synthesis_estimated_prompt_tokens"),
        },
        "citation": {
            "status": "available" if "citation_source_keys" in ctx else "unavailable",
            "response_source_count": len(ctx.get("response_source_keys", [])),
            "response_source_keys": ctx.get("response_source_keys", []),
            "cited_source_count": len(ctx.get("citation_source_keys", [])),
            "cited_source_keys": ctx.get("citation_source_keys", []),
        },
        "quality": _quality_lineage(ctx, response),
        "summary": _summary_lineage(ctx),
        "performance": _performance_lineage(ctx),
    }
    while _lineage_size(lineage) > max_bytes:
        stage = next(
            (item for item in reversed(stages) if item["candidates"]),
            None,
        )
        if stage is None:
            break
        stage["candidates"].pop()
        stage["truncated"] = True
        truncated = True
        serialized_candidate_count -= 1
        lineage["serialized_candidate_count"] = serialized_candidate_count
    lineage["truncated"] = truncated
    lineage["status"] = "truncated" if truncated else "available"
    return lineage["status"], lineage


def _quality_lineage(ctx: QueryContext, response: RAGResponse | None) -> dict[str, object]:
    status = (
        response.faithfulness_status
        if response is not None
        else ctx.get("faithfulness_status")
    )
    method = _context_execution_value(ctx, "faithfulness_checker")
    support_status_counts: dict[str, int] = {}
    claim_ids: set[str] = set()
    for source in response.sources if response is not None else ():
        for window in source.evidence_windows:
            support_status_counts[window.support_status] = (
                support_status_counts.get(window.support_status, 0) + 1
            )
            claim_ids.add(window.claim_id)
    citation_verification = response.citation_verification if response is not None else None
    claims = citation_verification.claims if citation_verification is not None else ()
    applicable_claims = len(claims)
    supported_claims = sum(c.verdict == "supported" for c in claims)
    unsupported_claims = sum(c.verdict == "unsupported" for c in claims)
    unknown_claims = sum(c.verdict == "unknown" for c in claims)
    cited_claims = sum(bool(c.source_labels or c.quotes) for c in claims)
    uncited_claims = applicable_claims - cited_claims
    valid_quotes = sum(len(c.quotes) for c in claims)
    claim_ledger = {
        "status": "captured" if citation_verification is not None else "not_captured",
        "applicable_claims": applicable_claims,
        "supported_claims": supported_claims,
        "unsupported_claims": unsupported_claims,
        "unknown_claims": unknown_claims,
        "cited_claims": cited_claims,
        "uncited_claims": uncited_claims,
        "valid_quotes": valid_quotes,
        "final_answer_claims": applicable_claims,
    }
    return {
        "status": status or "not_measured",
        "method": method,
        "score": (
            response.faithfulness_score
            if response is not None and status == "checked"
            else None
        ),
        "score_subject": "delivered_answer" if response is not None else None,
        "answer_replaced": bool(
            citation_verification is not None and citation_verification.repair_count > 0
        ),
        "support_status_counts": support_status_counts,
        "evidence_window_count": sum(support_status_counts.values()),
        "evidence_claim_count": len(claim_ids),
        "claim_ledger": claim_ledger,
        "claim_ledger_status": claim_ledger["status"],
        "citation_verification": ({
            "version": response.citation_verification.version,
            "answer_sha256": response.citation_verification.answer_sha256,
            "status": response.citation_verification.status,
            "repair_count": response.citation_verification.repair_count,
            "applicable_claims": len(response.citation_verification.claims),
            "supported_claims": sum(c.verdict == "supported" for c in response.citation_verification.claims),
            "unsupported_claims": sum(c.verdict == "unsupported" for c in response.citation_verification.claims),
            "unknown_claims": sum(c.verdict == "unknown" for c in response.citation_verification.claims),
            "valid_quotes": sum(len(c.quotes) for c in response.citation_verification.claims),
            "claims": [{"claim_id": c.claim_id, "verdict": c.verdict, "reason": c.reason,
                        "source_labels": c.source_labels, "quote_count": len(c.quotes)}
                       for c in response.citation_verification.claims],
        } if response is not None and response.citation_verification is not None else None),
        "citation_attempts": ctx.get("citation_diagnostics"),
    }


def _candidate_key(row: dict[str, object]) -> str:
    return ":".join(
        str(row.get(key) or "")
        for key in ("index_generation_id", "doc_id", "chunk_id", "point_id")
    )


def _cohort_text(cohort: dict[str, object], key: str) -> str | None:
    value = cohort.get(key)
    return value.strip()[:160] if isinstance(value, str) and value.strip() else None


def _coverage_unit_count(trace: list[RetrievalTraceStage]) -> int:
    return len(
        {
            candidate.coverage_unit_id
            for stage in trace
            for candidate in stage.candidates
            if candidate.coverage_unit_id
        }
    )


def _summary_lineage(ctx: QueryContext) -> dict[str, object]:
    contexts = ctx.get("summary_contexts")
    units = ctx.get("summary_context_units")
    if contexts is None:
        return {"status": "not_applicable"}
    return {
        "status": "available",
        "required_document_count": len(contexts),
        "required_context_unit_count": sum(len(unit) for unit in units or []),
        "retained_context_block_count": ctx.get("synthesis_context_count"),
    }


def _performance_lineage(ctx: QueryContext) -> dict[str, object]:
    timings = []
    for raw in ctx.get("node_timings", []):
        node = raw.get("node")
        duration = raw.get("duration_ms")
        if not isinstance(node, str) or not node.strip():
            continue
        if isinstance(duration, bool) or not isinstance(duration, int | float):
            continue
        phases = raw.get("phase_timings_ms")
        safe_phases = {
            str(name): max(0, int(value))
            for name, value in (phases.items() if isinstance(phases, dict) else ())
            if isinstance(name, str)
            and isinstance(value, int | float)
            and not isinstance(value, bool)
        }
        timings.append(
            {
                "node": node[:80],
                "duration_ms": max(0, int(duration)),
                "phase_timings_ms": safe_phases,
            }
        )
    return {
        "status": "available" if timings else "unavailable",
        "node_timings": timings,
    }


def _lineage_size(lineage: dict[str, object]) -> int:
    return len(json.dumps(lineage, ensure_ascii=True, separators=(",", ":")))
