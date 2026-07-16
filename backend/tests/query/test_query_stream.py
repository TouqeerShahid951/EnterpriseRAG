from itertools import islice
from types import SimpleNamespace
from time import perf_counter

from rag.auth.context import UserContext
from rag.query.qdrant import SearchHit
from rag.query.query_stream import _stream_response_tail, _stream_synthesizer, stream_graph
from rag.query.routing.routing_models import RoutePlan
from rag.query.state import QueryContext, initial_state
from rag.query.schemas import QueryRequest


class FakeStreamNodes:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def session_memory(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("session_memory")
        return ctx

    def source_resolver(self, ctx: QueryContext) -> QueryContext:
        self.calls.append("source_resolver")
        return ctx

    def intent_router(self, ctx: QueryContext) -> QueryContext:
        assert self.calls == ["session_memory", "source_resolver"]
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


class FakeSynthesizerNodes:
    def __init__(self, chunks: list[str]) -> None:
        self.ollama = FakeStreamingLlm(chunks)
        self.config = SimpleNamespace(
            rag_defer_faithfulness=False,
            rag_faithfulness_threshold=0.7,
        )

    def faithfulness_checker(self, ctx: QueryContext) -> QueryContext:
        return ctx

    def artifact_generator(self, ctx: QueryContext) -> QueryContext:
        return ctx

    def response_serializer(self, ctx: QueryContext) -> QueryContext:
        return ctx


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


def test_stream_graph_runs_source_resolver_before_intent_router() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="hello"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    nodes = FakeStreamNodes()

    events = list(islice(stream_graph(ctx, nodes), 5))

    assert [event.data for event in events if event.event == "trace"] == [
        {"trace_id": "trace", "session_id": "session"},
        {"node": "session_memory"},
        {"node": "source_resolver"},
        {"node": "intent_router"},
    ]
    assert nodes.calls == ["session_memory", "source_resolver", "intent_router"]


def test_stream_synthesizer_defers_non_prefix_citation_rewrite_to_done() -> None:
    ctx = context_with_evidence()
    nodes = FakeSynthesizerNodes(["Finding A ", "[wrong:source]."])

    events = list(_stream_synthesizer(ctx, nodes))
    events.extend(_stream_response_tail(ctx, nodes))

    token_text = "".join(str(event.data["text"]) for event in events if event.event == "token")
    done = next(event for event in events if event.event == "done")
    assert token_text == "Finding A [wrong:source]."
    assert done.data["answer"] == "Finding A. [report-a:1]"
    assert ctx["response"].answer == done.data["answer"]


def test_stream_synthesizer_emits_append_only_citation_suffix() -> None:
    ctx = context_with_evidence()
    nodes = FakeSynthesizerNodes(["Finding A."])

    events = list(_stream_synthesizer(ctx, nodes))

    token_texts = [event.data["text"] for event in events if event.event == "token"]
    assert token_texts == ["Finding A.", " [report-a:1]"]
    assert "".join(str(text) for text in token_texts) == ctx["response"].answer
