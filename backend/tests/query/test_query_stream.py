from itertools import islice
from time import perf_counter

from rag.auth.context import UserContext
from rag.query.query_stream import stream_graph
from rag.query.routing_models import RoutePlan
from rag.query.state import QueryContext, initial_state
from rag.schemas.query import QueryRequest


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
