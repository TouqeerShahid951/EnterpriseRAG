from time import perf_counter

from rag.auth.context import UserContext
from rag.query.qdrant import SearchHit
from rag.query.routing_models import RoutePlan
from rag.query.sources import sources_from_hits
from rag.query.state import initial_state
from rag.query.synthesis import prepare_synthesis_input
from rag.schemas.query import QueryRequest


def hit(point_id: str, *, doc_id: str, doc_title: str, text: str) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=0.5,
        payload={
            "doc_id": doc_id,
            "chunk_id": point_id,
            "doc_title": doc_title,
            "text": text,
            "page": 1,
            "exhaustive_scope_origin": "document_class_scope",
        },
    )


def test_scoped_aggregation_synthesis_requires_document_coverage() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list all findings from all reports"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit("report-a:1", doc_id="report-a", doc_title="Report A.pdf", text="Finding A."),
        hit("report-b:1", doc_id="report-b", doc_title="Report B.pdf", text="Finding B."),
    ]

    prepared = prepare_synthesis_input(ctx, sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query))

    assert "Evidence scope: exhaustive document-class scan." in prepared.question
    assert "Report A.pdf" in prepared.question
    assert "Report B.pdf" in prepared.question
    assert "Cover every scoped document represented in the evidence" in prepared.question
    assert any("Location: Document: Report A.pdf" in context for context in prepared.contexts)
