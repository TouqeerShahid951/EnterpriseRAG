"""State contract for the query orchestration graph."""

from __future__ import annotations

from dataclasses import replace
from typing import NotRequired, TypedDict

from ..auth.context import UserContext
from .schemas import ConflictPair, QueryIntent, QueryNodeTiming, QueryRequest, RAGResponse
from .artifact_intent import ArtifactRequest, parse_artifact_request, requires_document_scope
from .artifact_models import ArtifactContent, ArtifactPlan, ArtifactValidation, CoverageReport, EvidenceUnit
from .cancellation import QueryCancellationToken
from .evidence_quality import EvidenceQuality
from .qdrant import SearchHit
from .routing_models import QuerySignals, RoutePlan


class QueryContext(TypedDict):
    trace_id: str
    session_id: str
    request: QueryRequest
    user: UserContext
    cancellation_token: NotRequired[QueryCancellationToken]
    query_rewritten: list[str]
    intent: QueryIntent
    route_plan: NotRequired[RoutePlan]
    initial_route_intent: NotRequired[str]
    route_signals: NotRequired[QuerySignals]
    source_decision: NotRequired[object]
    source_expansion: NotRequired[dict[str, object]]
    route_reroute_count: int
    sub_queries: list[str]
    is_current_only: bool
    retrieved_hits: list[SearchHit]
    session_turns: list[dict[str, object]]
    node_trace: list[dict[str, str | None]]
    node_timings: list[dict[str, str | int | None]]
    execution_modes: dict[str, str]
    execution_details: dict[str, str]
    graphrag_communities: NotRequired[list[object]]
    retry_count: int
    token_budget: int
    wall_time_start: float
    verifier_decision: str
    evidence_quality: NotRequired[EvidenceQuality]
    conflict_checker_used: bool
    synthesis_profile: NotRequired[str]
    artifact_request: NotRequired[ArtifactRequest]
    artifact_plan: NotRequired[ArtifactPlan]
    artifact_evidence: NotRequired[tuple[EvidenceUnit, ...]]
    artifact_coverage: NotRequired[CoverageReport]
    artifact_content: NotRequired[ArtifactContent]
    artifact_validation: NotRequired[ArtifactValidation]
    conflict_flag: bool
    conflict_pairs: list[ConflictPair]
    faithfulness_score: float
    faithfulness_status: str
    unfounded_claims: list[str]
    degraded: bool
    degraded_reason: str | None
    response: NotRequired[RAGResponse]


def initial_state(
    *,
    trace_id: str,
    session_id: str,
    request: QueryRequest,
    user: UserContext,
    started: float,
    token_budget: int = 12000,
    cancellation_token: QueryCancellationToken | None = None,
) -> QueryContext:
    artifact_request = parse_artifact_request(request.query)
    if (
        artifact_request is not None
        and artifact_request.needs_clarification
        and request.document_ids
        and requires_document_scope(artifact_request.content_query)
    ):
        artifact_request = replace(artifact_request, needs_clarification=False)
    if artifact_request is not None and not artifact_request.needs_clarification:
        request = request.model_copy(update={"query": artifact_request.content_query})
    ctx: QueryContext = {
        "trace_id": trace_id,
        "session_id": session_id,
        "request": request,
        "user": user,
        "query_rewritten": [],
        "intent": "factual_simple",
        "route_reroute_count": 0,
        "sub_queries": [request.query],
        "is_current_only": True,
        "retrieved_hits": [],
        "session_turns": [],
        "node_trace": [],
        "node_timings": [],
        "execution_modes": {},
        "execution_details": {},
        "retry_count": 0,
        "token_budget": token_budget,
        "wall_time_start": started,
        "verifier_decision": "pass",
        "conflict_checker_used": False,
        "conflict_flag": False,
        "conflict_pairs": [],
        "faithfulness_score": 1.0,
        "faithfulness_status": "pending",
        "unfounded_claims": [],
        "degraded": False,
        "degraded_reason": None,
    }
    if artifact_request is not None:
        ctx["artifact_request"] = artifact_request
    if cancellation_token is not None:
        ctx["cancellation_token"] = cancellation_token
    return ctx


def scoped_user_context(ctx: QueryContext) -> UserContext:
    group_path = ctx["request"].group_path
    if not group_path:
        return ctx["user"]
    return UserContext(
        user_id=ctx["user"].user_id,
        email=ctx["user"].email,
        account_type=ctx["user"].account_type,
        group_paths=(group_path,),
        clearance_level=ctx["user"].clearance_level,
        permission_version=ctx["user"].permission_version,
    )


def visible_group_paths(ctx: QueryContext) -> tuple[str, ...]:
    return tuple(scoped_user_context(ctx).group_paths)


def record_node_timing(ctx: QueryContext, node: str, duration_ms: int) -> None:
    ctx["node_timings"].append({
        "node": node,
        "duration_ms": max(0, int(duration_ms)),
        "execution_mode": ctx["execution_modes"].get(node),
        "detail": ctx["execution_details"].get(node),
    })


def response_node_timings(ctx: QueryContext) -> list[QueryNodeTiming]:
    return [QueryNodeTiming.model_validate(item) for item in ctx["node_timings"]]


def finalize_response_node_timings(ctx: QueryContext) -> QueryContext:
    if "response" in ctx:
        ctx["response"] = ctx["response"].model_copy(update={
            "node_timings": response_node_timings(ctx),
        })
    return ctx
