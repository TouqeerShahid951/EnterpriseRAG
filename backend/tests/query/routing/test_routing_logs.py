from rag.auth.context import UserContext
from rag.query.routing.routing_logs import _source_routing_fields
from rag.query.schemas import QueryRequest
from rag.query.sources.source_resolution import SourceDecision
from rag.query.state import initial_state


def test_source_routing_fields_expose_final_route_and_expansion() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="Summarize the repair manual"),
        user=UserContext(
            user_id="user",
            email="user@example.test",
            group_paths=("/ops",),
        ),
        started=0.0,
    )
    ctx["source_decision"] = SourceDecision(
        requested_mode="auto",
        resolved_mode="hybrid",
        semantic_query=ctx["request"].query,
        explicit=False,
        reason="auto_corpus_first_corpus_preferred:evidence_expansion",
        structured_score=0,
        corpus_score=2,
        source_match_score=0,
        document_match_score=3,
        preferred_source="corpus",
        routing_confidence=0.9,
    )
    ctx["execution_modes"]["live_sql_retriever"] = "ai_assisted"

    fields = _source_routing_fields(ctx)

    assert fields["requested_source_mode"] == "auto"
    assert fields["resolved_source_mode"] == "hybrid"
    assert fields["source_expansion_performed"] is True
    assert fields["source_signal_scores"] == {
        "structured": 0,
        "corpus": 2,
        "source_match": 0,
        "document_match": 3,
    }
    assert fields["live_sql_mode"] == "ai_assisted"
