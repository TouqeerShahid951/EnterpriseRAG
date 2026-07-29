from itertools import islice
from types import SimpleNamespace
from time import perf_counter

from rag.auth.context import UserContext
from rag.graphrag.graphrag_synthesizer import synthesize_graphrag_response
from rag.graphrag.models import CommunitySummary, SourceRef
from rag.graphrag.qdrant import CommunitySearchHit
from rag.query.qdrant import SearchHit
from rag.query.query_stream import _stream_response_tail, _stream_synthesizer, stream_graph
from rag.query.routing.routing_models import RoutePlan
from rag.query.routing.conversation_resolution import ConversationResolution
from rag.query.state import QueryContext, initial_state
from rag.query.schemas import QueryRequest, RAGResponse


class FakeStreamNodes:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def session_memory(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("session_memory")
        return ctx

    def source_resolver(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("source_resolver")
        return ctx

    def conversation_resolver(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("conversation_resolver")
        return ctx

    def intent_router(self, ctx: QueryContext) -> QueryContext:
        assert self.calls == [
            "session_memory",
            "conversation_resolver",
            "source_resolver",
        ]
        self.calls.append("intent_router")
        ctx["route_plan"] = RoutePlan(
            original_query=ctx["request"].query,
            resolved_query=ctx["request"].query,
            intent="out_of_scope",
            public_intent="conversational",
            needs_retrieval=False,
            top_k=0,
        )
        ctx["intent"] = "conversational"
        return ctx


class FakeStreamingLlm:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    def stream_answer(self, **_: object):
        yield from self.chunks

    def answer(self, **_: object):
        return "".join(self.chunks)


class FakeSynthesizerNodes:
    def __init__(self, chunks: list[str], *, faithfulness_answer: str | None = None) -> None:
        self.ollama = FakeStreamingLlm(chunks)
        self.config = SimpleNamespace()
        self.specialized_synthesizer_called = False
        self.faithfulness_answer = faithfulness_answer

    def synthesizer(self, ctx: QueryContext) -> QueryContext:
        self.specialized_synthesizer_called = True
        return synthesize_graphrag_response(ctx, self.ollama)

    def faithfulness_checker(self, ctx: QueryContext) -> QueryContext:
        if self.faithfulness_answer is not None:
            ctx["response"] = ctx["response"].model_copy(update={"answer": self.faithfulness_answer})
        return ctx

    def should_run_faithfulness(self, ctx: QueryContext) -> bool:
        return bool(ctx["response"].sources)

    def response_serializer(self, ctx: QueryContext) -> QueryContext:
        return ctx


class FakeEvidenceGateNodes(FakeSynthesizerNodes):
    def __init__(self) -> None:
        super().__init__(["Finding A. [report-a:1]"])
        self.calls: list[str] = []

    def _record(self, name: str, ctx: QueryContext) -> QueryContext:
        self.calls.append(name)
        return ctx

    def session_memory(self, ctx: QueryContext) -> QueryContext:
        return self._record("session_memory", ctx)

    def source_resolver(self, ctx: QueryContext) -> QueryContext:
        return self._record("source_resolver", ctx)

    def conversation_resolver(self, ctx: QueryContext) -> QueryContext:
        return self._record("conversation_resolver", ctx)

    def intent_router(self, ctx: QueryContext) -> QueryContext:
        self._record("intent_router", ctx)
        ctx["intent"] = "factual_simple"
        ctx["route_plan"] = RoutePlan(
            original_query=ctx["request"].query,
            resolved_query=ctx["request"].query,
            intent="general_rag",
        )
        return ctx

    def abac_retriever(self, ctx: QueryContext) -> QueryContext:
        self._record("abac_retriever", ctx)
        ctx["retrieved_hits"] = context_with_evidence()["retrieved_hits"]
        return ctx

    def reranker(self, ctx: QueryContext) -> QueryContext:
        return self._record("reranker", ctx)

    def verifier(self, ctx: QueryContext) -> QueryContext:
        self._record("verifier", ctx)
        ctx["verifier_decision"] = "pass"
        return ctx

    def temporal_resolver(self, ctx: QueryContext) -> QueryContext:
        return self._record("temporal_resolver", ctx)

    def evidence_builder(self, ctx: QueryContext) -> QueryContext:
        return self._record("evidence_builder", ctx)

    def evidence_gate(self, ctx: QueryContext) -> QueryContext:
        self._record("evidence_gate", ctx)
        if self.calls.count("evidence_gate") == 1:
            ctx["retry_count"] += 1
            ctx["verifier_decision"] = "retry"
        else:
            ctx["verifier_decision"] = "pass"
        return ctx

    def contradiction_detector(self, ctx: QueryContext) -> QueryContext:
        return self._record("contradiction_detector", ctx)

    def faithfulness_checker(self, ctx: QueryContext) -> QueryContext:
        self._record("faithfulness_checker", ctx)
        return super().faithfulness_checker(ctx)

    def response_serializer(self, ctx: QueryContext) -> QueryContext:
        return self._record("response_serializer", ctx)


def context_with_evidence() -> QueryContext:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="What is finding A?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["retrieved_hits"] = [
        SearchHit(
            point_id="report-a:1",
            score=0.9,
            payload={
                "doc_id": "report-a",
                "chunk_id": "report-a:1",
                "doc_title": "Report A.pdf",
                "text": "Finding A.",
                "page": 1,
            },
        )
    ]
    return ctx


def context_with_database_evidence() -> QueryContext:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="Which demo case has the highest priority?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["retrieved_hits"] = [
        SearchHit(
            point_id="connector-live-scope:catalog:query:0",
            score=1.0,
            payload={
                "doc_id": "connector-live-scope:catalog",
                "chunk_id": "connector-live-scope:catalog:query:0",
                "doc_title": "Live connector query: Demo cases",
                "text": "case_id: DEMO-ALPHA\nstatus: Escalated\nassigned_team: Phoenix\noutstanding_amount: 1250.75",
                "source_type": "connector_live_sql_database_scope",
                "structured_kind": "kv_record",
                "structured_fields": [
                    {"label": "case_id", "value": "DEMO-ALPHA"},
                    {"label": "status", "value": "Escalated"},
                    {"label": "assigned_team", "value": "Phoenix"},
                    {"label": "outstanding_amount", "value": "1250.75"},
                ],
            },
        )
    ]
    return ctx


def test_stream_graph_runs_source_resolver_before_intent_router() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="hello"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    nodes = FakeStreamNodes()

    events = list(islice(stream_graph(ctx, nodes), 6))

    assert [event.data for event in events if event.event == "trace"] == [
        {"trace_id": "trace", "session_id": "session"},
        {"node": "session_memory"},
        {"node": "conversation_resolver"},
        {"node": "source_resolver"},
        {"node": "intent_router"},
    ]
    assert nodes.calls == [
        "session_memory",
        "conversation_resolver",
        "source_resolver",
        "intent_router",
    ]


def test_stream_graph_retries_after_evidence_gate_before_synthesis() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="What is finding A?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    nodes = FakeEvidenceGateNodes()

    events = list(stream_graph(ctx, nodes))

    assert nodes.calls == [
        "session_memory",
        "conversation_resolver",
        "source_resolver",
        "intent_router",
        "abac_retriever",
        "reranker",
        "verifier",
        "temporal_resolver",
        "evidence_builder",
        "evidence_gate",
        "abac_retriever",
        "reranker",
        "verifier",
        "temporal_resolver",
        "evidence_builder",
        "evidence_gate",
        "contradiction_detector",
        "faithfulness_checker",
        "response_serializer",
    ]
    assert [event.data["code"] for event in events if event.event == "warning"] == ["verifier_retry"]
    assert [event.data["text"] for event in events if event.event == "token"] == [ctx["response"].answer]


class FakeClarificationNodes(FakeSynthesizerNodes):
    def __init__(self) -> None:
        super().__init__([])
        self.calls: list[str] = []

    def session_memory(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("session_memory")
        return ctx

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
        ctx["intent"] = "conversational"
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


def test_stream_graph_clarifies_without_source_or_retrieval_events() -> None:
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
    nodes = FakeClarificationNodes()

    events = list(stream_graph(ctx, nodes))

    assert nodes.calls == [
        "session_memory",
        "conversation_resolver",
        "conversation_clarifier",
        "response_serializer",
    ]
    assert not [event for event in events if event.event == "source"]
    assert next(event for event in events if event.event == "done").data[
        "answer_status"
    ] == "clarification"


def test_stream_synthesizer_emits_only_validated_citation_rewrite() -> None:
    ctx = context_with_evidence()
    nodes = FakeSynthesizerNodes(["Finding A ", "[wrong:source]."])

    events = list(_stream_synthesizer(ctx, nodes))
    events.extend(_stream_response_tail(ctx, nodes))

    token_text = "".join(str(event.data["text"]) for event in events if event.event == "token")
    done = next(event for event in events if event.event == "done")
    assert token_text == "Finding A. [report-a:1]"
    assert done.data["answer"] == "Finding A. [report-a:1]"
    assert ctx["response"].answer == done.data["answer"]


def test_stream_synthesizer_emits_one_authoritative_answer_token() -> None:
    ctx = context_with_evidence()
    nodes = FakeSynthesizerNodes(["Finding A."])

    events = list(_stream_synthesizer(ctx, nodes))
    events.extend(_stream_response_tail(ctx, nodes))

    token_texts = [event.data["text"] for event in events if event.event == "token"]
    assert token_texts == ["Finding A. [report-a:1]"]
    assert token_texts[0] == ctx["response"].answer


def test_stream_synthesizer_does_not_leak_answer_rejected_by_faithfulness() -> None:
    ctx = context_with_evidence()
    nodes = FakeSynthesizerNodes(
        ["An unsupported answer. [report-a:1]"],
        faithfulness_answer="I could not verify this answer.",
    )
    events = list(_stream_synthesizer(ctx, nodes))
    events.extend(_stream_response_tail(ctx, nodes))

    assert [event.data["text"] for event in events if event.event == "token"] == [
        "I could not verify this answer."
    ]
    assert next(event for event in events if event.event == "done").data["answer"] == (
        "I could not verify this answer."
    )
    assert all(event.event != "verified" for event in events)


def test_stream_synthesizer_uses_graphrag_synthesis_when_available() -> None:
    ctx = context_with_evidence()
    ctx["graphrag_communities"] = [
        CommunitySearchHit(
            id="community-point-1",
            score=1.0,
            summary=CommunitySummary(
                id="summary-1",
                community_id="community-1",
                partition_key="/admin|clearance:1",
                group_path="/admin",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
                level=0,
                title="Finding pattern",
                summary="Finding A is recurring.",
                source_refs=[
                    SourceRef(doc_id="report-a", chunk_id="report-a:1")
                ],
            ),
        )
    ]
    nodes = FakeSynthesizerNodes(["Finding A recurs. [report-a:1]"])

    events = list(_stream_synthesizer(ctx, nodes))
    events.extend(_stream_response_tail(ctx, nodes))

    assert nodes.specialized_synthesizer_called is True
    assert [event.data["text"] for event in events if event.event == "token"] == [ctx["response"].answer]
    assert ctx["synthesis_profile"] == "graphrag_global"


def test_stream_synthesizer_replaces_citation_only_database_answer() -> None:
    ctx = context_with_database_evidence()
    citation = "[connector-live-scope:catalog:query:0]"
    nodes = FakeSynthesizerNodes([citation])

    events = list(_stream_synthesizer(ctx, nodes))
    events.extend(_stream_response_tail(ctx, nodes))

    token_text = "".join(str(event.data["text"]) for event in events if event.event == "token")
    done = next(event for event in events if event.event == "done")
    assert token_text == done.data["answer"]
    assert done.data["answer"] == (
        "case_id: DEMO-ALPHA; status: Escalated; assigned_team: Phoenix; "
        f"outstanding_amount: 1250.75 {citation}."
    )
    assert done.data["answer_status"] == "complete"
