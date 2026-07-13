from time import perf_counter

from rag.auth.context import UserContext
from rag.graphrag.graphrag_synthesizer import synthesize_graphrag_response
from rag.graphrag.models import CommunitySummary, SourceRef
from rag.graphrag.qdrant import CommunitySearchHit
from rag.query.qdrant import SearchHit
from rag.query.routing_models import RoutePlan
from rag.query.state import initial_state
from rag.query.schemas import QueryRequest


class UncitedAnswerModel:
    def answer(self, *, question, contexts, profile=None, cancellation_token=None):
        return "The corpus shows an operational coordination pattern."


def test_graphrag_synthesis_degrades_uncited_graph_claims() -> None:
    ctx = initial_state(
        trace_id="trace-1",
        session_id="session-1",
        request=QueryRequest(query="What patterns appear?", group_path="/ops"),
        user=UserContext(
            user_id="user-1",
            email="user@example.com",
            group_paths=("/ops",),
            clearance_level="NATO_RESTRICTED",
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="graphrag_global",
        retrieval_strategy="graphrag_global",
        public_intent="aggregation",
    )
    ctx["graphrag_communities"] = [
        CommunitySearchHit(
            id="community-point-1",
            score=1.0,
            summary=CommunitySummary(
                id="summary-1",
                community_id="community-1",
                partition_key="/ops|clearance:1",
                group_path="/ops",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
                level=0,
                title="Coordination",
                summary="Coordination appears in the source.",
                source_refs=[SourceRef(doc_id="doc-1", chunk_id="chunk-1")],
            ),
        )
    ]
    ctx["retrieved_hits"] = [
        SearchHit(
            point_id="point-1",
            score=1.0,
            payload={
                "doc_id": "doc-1",
                "chunk_id": "chunk-1",
                "doc_title": "Doc",
                "text": "Coordination appears in the source.",
                "group_path": "/ops",
                "clearance_level": "NATO_RESTRICTED",
                "clearance_rank": 1,
                "is_current": True,
            },
        )
    ]

    synthesize_graphrag_response(ctx, UncitedAnswerModel())

    assert ctx["response"].degraded is True
    assert ctx["response"].degraded_reason == "graphrag_uncited_answer"
    assert "[doc-1:chunk-1]" in ctx["response"].answer
    assert ctx["response"].sources[0].doc_id == "doc-1"
