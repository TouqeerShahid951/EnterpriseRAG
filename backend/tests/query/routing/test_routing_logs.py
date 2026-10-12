from rag.auth.context import UserContext
from rag.query.routing import routing_logs
from rag.query.routing.conversation_resolution import ConversationResolution
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


def test_conversation_log_exposes_bounded_decision_diagnostics(monkeypatch) -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="Tell me more"),
        user=UserContext(
            user_id="user",
            email="user@example.test",
            group_paths=("/ops",),
        ),
        started=0.0,
    )
    ctx["conversation_resolution"] = ConversationResolution(
        relation="ambiguous",
        effective_query="Tell me more",
        clarification_question="Which earlier answer do you mean?",
        method="fallback",
        context_turn_count=1,
        decision_reason="fallback",
        model_attempt_count=1,
        fallback_error_code="invalid_output",
    )
    payloads: list[dict[str, object]] = []
    monkeypatch.setattr(routing_logs, "_log_info", payloads.append)

    routing_logs.log_conversation_resolution(ctx)

    assert payloads[0]["decision_reason"] == "fallback"
    assert payloads[0]["model_attempt_count"] == 1
    assert payloads[0]["fallback_error_code"] == "invalid_output"
    assert payloads[0]["query_changed"] is False
    assert "query" not in payloads[0]
