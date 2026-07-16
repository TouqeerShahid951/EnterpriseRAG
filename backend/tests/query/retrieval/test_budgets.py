# ruff: noqa: F403, F405

from query_retrieval_scope_support import *


def test_expired_scope_scan_records_structured_incomplete_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag.query.retrieval.query_retrieval.exhaustive_retrieval_deadline",
        lambda _started: 0.0,
    )
    qdrant = FakeExpiredBroadQdrant()
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="Summarize all documents"),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(ctx["request"].query)

    retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=FakeEmbedder(),
        qdrant=qdrant,
    )

    assert ctx["degraded"] is True
    assert ctx["degraded_reason"] == "exhaustive_scope_scan_truncated"
    assert ctx["exhaustive_coverage"]["candidate_status"] == "partial"
    assert ctx["exhaustive_coverage"]["evidence_status"] == "unknown"
