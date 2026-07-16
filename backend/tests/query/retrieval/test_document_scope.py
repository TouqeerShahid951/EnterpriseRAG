# ruff: noqa: F403, F405

from query_retrieval_scope_support import *


def test_exhaustive_aggregation_expands_named_document_scope() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(
            query="List All the Crime Commited with details in the all FIRs"
        ),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(ctx["request"].query)

    hits = retrieve_candidates(
        ctx, config=FakeConfig(), ollama=FakeEmbedder(), qdrant=FakeQdrant()
    )

    doc_ids = {item.payload["doc_id"] for item in hits}
    assert {"fir-01", "fir-02", "fir-03", "fir-04", "fir-05"} <= doc_ids
    assert "manual" not in doc_ids
    assert all(
        item.payload.get("exhaustive_scope_origin") == "document_class_scope"
        for item in hits
        if item.payload["doc_id"].startswith("fir-")
    )

def test_exhaustive_document_scope_is_doc_type_agnostic() -> None:
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
        ctx, config=FakeConfig(), ollama=FakeEmbedder(), qdrant=FakeManualQdrant()
    )

    doc_ids = {item.payload["doc_id"] for item in hits}
    assert doc_ids == {"manual-a", "manual-b"}
    assert all(
        item.payload.get("exhaustive_scope_origin") == "document_class_scope"
        for item in hits
    )

def test_named_exhaustive_scope_uses_authorized_document_scan() -> None:
    qdrant = FakeScopedManualQdrant()
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(
            query="Give me a list of all equipment required to repair a Samsung device"
        ),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
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

    assert qdrant.document_scan is not None
    assert qdrant.document_scan["document_ids"] == ["samsung"]
    must = qdrant.document_scan["qdrant_filter"]["must"]
    assert any(
        nested.get("key") in {"acl_group_paths", "group_path"}
        for condition in must
        for nested in condition.get("should", [])
    )
    assert any(condition.get("key") == "clearance_rank" for condition in must)
    assert any(condition.get("key") == "is_current" for condition in must)
    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert hits[0].payload["exhaustive_scope_origin"] == "document_class_scope"

def test_explicit_document_scope_is_not_discarded_by_query_reinference() -> None:
    qdrant = FakeScopedManualQdrant()
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(
            query="List all equipment required to repair the device",
            document_ids=["samsung"],
        ),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
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

    assert qdrant.document_scan is not None
    assert qdrant.document_scan["document_ids"] == ["samsung"]
    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert "samsung:tools" in {item.payload["chunk_id"] for item in hits}
    assert (
        next(
            item for item in hits if item.payload["chunk_id"] == "samsung:tools"
        ).payload["exhaustive_scope_origin"]
        == "document_class_scope"
    )

def test_named_scope_can_be_resolved_after_initial_semantic_miss() -> None:
    qdrant = FakeSamsungSemanticMissQdrant()
    query = (
        "Give me a list of all the equipments required to repair a samsung. "
        "Dont skip or miss any."
    )
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(query)

    hits = retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=FakeEmbedder(),
        qdrant=qdrant,
    )

    assert qdrant.authorized_scan_called is True
    assert qdrant.document_scan_called is False
    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert hits[0].payload["exhaustive_scope_origin"] == "document_class_scope"

def test_long_action_phrase_does_not_hide_named_document_scope() -> None:
    qdrant = FakeSamsungSemanticMissQdrant()
    query = (
        "List all equipment needed to properly diagnose and repair a "
        "Samsung Galaxy S24 device"
    )
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
        ),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(query)

    hits = retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=FakeEmbedder(),
        qdrant=qdrant,
    )

    assert qdrant.authorized_scan_called is True
    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert ctx["degraded"] is False

def test_broad_document_scope_focuses_on_subject_tokens() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(
            query="What are all the soldiers doing in all the documents?"
        ),
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
        qdrant=FakeBroadDocumentQdrant(),
    )

    doc_ids = {item.payload["doc_id"] for item in hits}
    assert doc_ids == {"image"}
    assert hits[0].payload.get("exhaustive_scope_origin") == "document_class_scope"
    assert "soldier" in hits[0].payload["text"].lower()

def test_broad_scope_focus_expands_the_entire_matching_section() -> None:
    query = "List all equipment in all documents"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
        ),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(query)

    hits = retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=FakeEmbedder(),
        qdrant=FakeBroadSectionQdrant(),
    )

    assert {item.payload["chunk_id"] for item in hits} == {
        "manual:tools-heading",
        "manual:goggles",
        "manual:mat",
        "manual:gloves",
    }

def test_broad_document_summary_scope_still_keeps_all_documents() -> None:
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
        ctx, config=FakeConfig(), ollama=FakeEmbedder(), qdrant=FakeBroadSummaryQdrant()
    )

    doc_ids = {item.payload["doc_id"] for item in hits}
    assert doc_ids == {"policy", "climate", "image"}
    assert all(
        item.payload.get("exhaustive_scope_origin") == "document_class_scope"
        for item in hits
    )

def test_unresolved_named_scope_cannot_fall_back_to_generic_document_kind() -> None:
    qdrant = FakeWrongNamedScopeQdrant()
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="List all equipment from Acme manual"),
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

    assert hits == []
    assert qdrant.authorized_scan_called is True
    assert qdrant.document_scan_called is False
    assert ctx["degraded"] is True
    assert ctx["degraded_reason"] == "exhaustive_scope_unresolved"
    assert ctx["exhaustive_coverage"]["evidence_status"] == "unknown"
