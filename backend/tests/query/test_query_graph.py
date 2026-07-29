from time import perf_counter
from typing import cast

from rag.auth.context import UserContext
from rag.query.graph import QueryGraphRunner
from rag.query.nodes import QueryNodes
from rag.query.routing.routing_models import RoutePlan
from rag.query.routing.conversation_resolution import ConversationResolution
from rag.query.schemas import QueryRequest, RAGResponse
from rag.query.state import QueryContext, initial_state


class RecordingNodes:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def run(ctx: QueryContext) -> QueryContext:
            self.calls.append(name)
            if name == "intent_router":
                ctx["intent"] = "multi_hop"
                ctx["route_plan"] = RoutePlan(
                    original_query=ctx["request"].query,
                    resolved_query=ctx["request"].query,
                    intent="multi_hop",
                    use_query_planner=True,
                    public_intent="multi_hop",
                )
            elif name == "abac_retriever":
                ctx["retrieval_phase_timings_ms"] = {
                    "embeddings": 1,
                    "vector_search": 2,
                }
            elif name == "verifier":
                ctx["verifier_decision"] = "retry" if self.calls.count(name) == 1 else "pass"
            elif name == "response_serializer":
                ctx["response"] = RAGResponse(
                    trace_id=ctx["trace_id"],
                    answer="answer",
                    conflict_flag=False,
                    faithfulness_score=1.0,
                    intent=ctx["intent"],
                    session_id=ctx["session_id"],
                    latency_ms=0,
                    degraded=False,
                )
            return ctx

        return run


def test_query_runner_preserves_planning_retry_and_response_order() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="Compare the findings"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    nodes = RecordingNodes()

    result = QueryGraphRunner(cast(QueryNodes, nodes)).invoke(ctx)

    expected = [
        "session_memory",
        "conversation_resolver",
        "source_resolver",
        "intent_router",
        "query_planner",
        "abac_retriever",
        "reranker",
        "verifier",
        "abac_retriever",
        "reranker",
        "verifier",
        "temporal_resolver",
        "evidence_builder",
        "evidence_gate",
        "synthesizer",
        "faithfulness_checker",
        "response_serializer",
    ]
    assert nodes.calls == expected
    assert [timing.node for timing in result["response"].node_timings] == expected
    retrieval_timings = [
        timing
        for timing in result["response"].node_timings
        if timing.node == "abac_retriever"
    ]
    assert all(
        timing.phase_timings_ms == {"embeddings": 1, "vector_search": 2}
        for timing in retrieval_timings
    )


class ClarificationNodes(RecordingNodes):
    def conversation_resolver(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("conversation_resolver")
        ctx["conversation_resolution"] = ConversationResolution(
            relation="ambiguous",
            effective_query=ctx["request"].query,
            clarification_question="Which policy do you mean?",
            method="rules",
            context_turn_count=2,
        )
        return ctx

    def conversation_clarifier(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("conversation_clarifier")
        ctx["response"] = RAGResponse(
            trace_id=ctx["trace_id"],
            answer="Which policy do you mean?",
            answer_status="clarification",
            conflict_flag=False,
            faithfulness_score=0.0,
            faithfulness_status="skipped",
            intent="conversational",
            session_id=ctx["session_id"],
            latency_ms=0,
            degraded=False,
        )
        return ctx

    def response_serializer(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("response_serializer")
        return ctx


def test_query_runner_clarifies_without_routing_or_retrieval() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="Why?"),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
        ),
        started=perf_counter(),
    )
    nodes = ClarificationNodes()

    result = QueryGraphRunner(cast(QueryNodes, nodes)).invoke(ctx)

    assert nodes.calls == [
        "session_memory",
        "conversation_resolver",
        "conversation_clarifier",
        "response_serializer",
    ]
    assert result["response"].answer_status == "clarification"
