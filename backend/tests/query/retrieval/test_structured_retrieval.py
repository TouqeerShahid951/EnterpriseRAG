# ruff: noqa: F403, F405

from query_retrieval_scope_support import *


def test_document_class_scope_enumerates_before_filtering_with_real_adapter() -> None:
    qdrant = FakeRealAdapterManualQdrant()
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="List all maintenance details from all manuals"),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(ctx["request"].query)

    hits = retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=FakeEmbedder(),
        qdrant=qdrant,
    )

    assert qdrant.authorized_scan_called is True
    assert qdrant.document_scan_called is False
    assert {item.payload["doc_id"] for item in hits} == {"manual-a", "manual-b"}

def test_broad_scope_uses_global_authorized_scan_with_real_adapter_shape() -> None:
    qdrant = FakeRealAdapterBroadQdrant()
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

    hits = retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=FakeEmbedder(),
        qdrant=qdrant,
    )

    assert qdrant.authorized_scan_called is True
    assert qdrant.document_scan_called is False
    assert {item.payload["doc_id"] for item in hits} == {"doc-a", "doc-b"}
    assert ctx["degraded"] is False
