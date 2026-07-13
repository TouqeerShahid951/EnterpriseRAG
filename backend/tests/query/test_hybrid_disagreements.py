from time import perf_counter

from rag.auth.context import UserContext
from rag.query.conflicts import apply_hybrid_disagreement_detection
from rag.query.qdrant import SearchHit
from rag.query.source_resolution import SourceDecision
from rag.query.state import initial_state
from rag.query.schemas import QueryRequest


def test_hybrid_disagreement_detection_flags_db_document_status_conflict() -> None:
    ctx = _ctx("What is the status?")
    ctx["retrieved_hits"] = [
        _db_hit("pending_internal"),
        _doc_hit("The ticket status: closed."),
    ]

    apply_hybrid_disagreement_detection(ctx)

    assert ctx["conflict_flag"] is True
    assert ctx["conflict_pairs"][0].attribute == "status"
    assert ctx["conflict_pairs"][0].value_a == "pending_internal"
    assert ctx["conflict_pairs"][0].value_b == "closed"


def test_hybrid_disagreement_detection_keeps_agreeing_sources_normal() -> None:
    ctx = _ctx("What is the status?")
    ctx["retrieved_hits"] = [
        _db_hit("pending_internal"),
        _doc_hit("The ticket status: pending_internal."),
    ]

    apply_hybrid_disagreement_detection(ctx)

    assert ctx["conflict_flag"] is False
    assert ctx["conflict_pairs"] == []


def _ctx(query: str):
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(user_id="user", email="user@example.test", group_paths=("/ops",)),
        started=perf_counter(),
    )
    ctx["source_decision"] = SourceDecision(
        requested_mode="auto",
        resolved_mode="hybrid",
        semantic_query=query,
        explicit=False,
        reason="auto_hybrid_balanced_preferred",
        allow_source_expansion=False,
    )
    return ctx


def _db_hit(status: str) -> SearchHit:
    return SearchHit(
        point_id="db:1",
        score=1.0,
        payload={
            "doc_id": "connector-live-scope:catalog",
            "chunk_id": "db:1",
            "doc_title": "Live connector query: Cases",
            "text": f"status: {status}",
            "source_type": "connector_live_sql_database_scope",
            "group_path": "/ops",
            "clearance_level": "NATO_RESTRICTED",
            "structured_fields": [{"label": "status", "value": status}],
        },
    )


def _doc_hit(text: str) -> SearchHit:
    return SearchHit(
        point_id="doc:1",
        score=0.8,
        payload={
            "doc_id": "doc",
            "chunk_id": "doc:1",
            "doc_title": "Support handbook",
            "text": text,
            "group_path": "/ops",
            "clearance_level": "NATO_RESTRICTED",
        },
    )
