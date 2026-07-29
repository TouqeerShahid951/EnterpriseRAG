"""State contract for the query orchestration graph."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import NotRequired, TypedDict

from ..auth.context import UserContext
from ..shared.contracts.evidence import ConflictPair
from .cancellation import QueryCancellationToken
from rag.query.answering.evidence_sufficiency import EvidenceSufficiencyResult
from rag.query.answering.evidence_quality import EvidenceQuality
from .qdrant import SearchHit
from rag.query.retrieval.retrieval_trace import RetrievalTraceStage
from rag.query.routing.routing_models import QuerySignals, RoutePlan
from rag.query.routing.conversation_resolution import ConversationResolution
from .schemas import QueryIntent, QueryNodeTiming, QueryRequest, RAGResponse


class ExhaustiveCoverageState(TypedDict):
    candidate_status: str
    evidence_status: str
    reasons: list[str]
    required_obligations: list[str]
    covered_obligations: list[str]


class QueryContext(TypedDict):
    trace_id: str
    session_id: str
    request: QueryRequest
    effective_query: str
    user: UserContext
    cancellation_token: NotRequired[QueryCancellationToken]
    query_rewritten: list[str]
    intent: QueryIntent
    route_plan: NotRequired[RoutePlan]
    initial_route_intent: NotRequired[str]
    route_signals: NotRequired[QuerySignals]
    source_decision: NotRequired[object]
    source_expansion: NotRequired[dict[str, object]]
    source_expansion_from: NotRequired[str]
    source_primary_hits: NotRequired[list[SearchHit]]
    abbreviation_query: NotRequired[str]
    abbreviation_glossary_hits: NotRequired[list[SearchHit]]
    route_reroute_count: int
    sub_queries: list[str]
    is_current_only: bool
    retrieved_hits: list[SearchHit]
    retrieval_trace: NotRequired[list[RetrievalTraceStage]]
    exhaustive_coverage: NotRequired[ExhaustiveCoverageState]
    exhaustive_deadline: NotRequired[float]
    force_faithfulness_check: bool
    session_turns: list[dict[str, object]]
    conversation_resolution: NotRequired[ConversationResolution]
    node_trace: list[dict[str, str | None]]
    node_timings: list[dict[str, object]]
    retrieval_phase_timings_ms: NotRequired[dict[str, int]]
    reranker_candidate_limit: NotRequired[int]
    reranker_candidate_count: NotRequired[int]
    reranker_input_characters: NotRequired[int]
    reranker_passage_max_characters: NotRequired[int]
    reranker_batch_count: NotRequired[int]
    reranker_stop_reason: NotRequired[str | None]
    synthesis_source_limit: NotRequired[int]
    synthesis_token_limit: NotRequired[int]
    synthesis_context_count: NotRequired[int]
    synthesis_estimated_prompt_tokens: NotRequired[int]
    required_query_slot_count: NotRequired[int]
    covered_query_slot_count: NotRequired[int]
    execution_modes: dict[str, str]
    execution_details: dict[str, str]
    graphrag_communities: NotRequired[list[object]]
    retry_count: int
    token_budget: int
    wall_time_start: float
    verifier_decision: str
    evidence_quality: NotRequired[EvidenceQuality]
    evidence_sufficiency: NotRequired[EvidenceSufficiencyResult]
    conflict_checker_used: bool
    synthesis_profile: NotRequired[str]
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
    capture_retrieval_trace: bool = False,
    force_faithfulness_check: bool = False,
) -> QueryContext:
    ctx: QueryContext = {
        "trace_id": trace_id,
        "session_id": session_id,
        "request": request,
        "effective_query": request.query,
        "user": user,
        "query_rewritten": [],
        "intent": "factual_simple",
        "route_reroute_count": 0,
        "sub_queries": [request.query],
        "is_current_only": True,
        "retrieved_hits": [],
        "force_faithfulness_check": force_faithfulness_check,
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
        "faithfulness_score": 0.0,
        "faithfulness_status": "pending",
        "unfounded_claims": [],
        "degraded": False,
        "degraded_reason": None,
    }
    if cancellation_token is not None:
        ctx["cancellation_token"] = cancellation_token
    if capture_retrieval_trace:
        ctx["retrieval_trace"] = []
    return ctx


def active_query(ctx: QueryContext) -> str:
    return ctx["effective_query"]


def initial_retrieval_state(
    *,
    trace_id: str,
    session_id: str,
    query: str,
    group_path: str | None,
    document_ids: tuple[str, ...],
    user: UserContext,
    token_budget: int,
) -> QueryContext:
    return initial_state(
        trace_id=trace_id,
        session_id=session_id,
        request=QueryRequest(
            query=query,
            session_id=session_id,
            group_path=group_path,
            document_ids=list(document_ids),
        ),
        user=user,
        started=0.0,
        token_budget=token_budget,
    )


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
    timing: dict[str, object] = {
        "node": node,
        "duration_ms": max(0, int(duration_ms)),
        "execution_mode": ctx["execution_modes"].get(node),
        "detail": ctx["execution_details"].get(node),
    }
    if node == "abac_retriever":
        phases = ctx.pop("retrieval_phase_timings_ms", {})
        if phases:
            timing["phase_timings_ms"] = dict(phases)
    ctx["node_timings"].append(timing)


@contextmanager
def timed_retrieval_phase(ctx: QueryContext, phase: str) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        elapsed_ms = max(0, int((perf_counter() - started) * 1000))
        phases = ctx.setdefault("retrieval_phase_timings_ms", {})
        phases[phase] = phases.get(phase, 0) + elapsed_ms


def response_node_timings(ctx: QueryContext) -> list[QueryNodeTiming]:
    return [QueryNodeTiming.model_validate(item) for item in ctx["node_timings"]]


def finalize_response_node_timings(ctx: QueryContext) -> QueryContext:
    if "response" in ctx:
        ctx["response"] = ctx["response"].model_copy(
            update={
                "node_timings": response_node_timings(ctx),
            }
        )
    return ctx
