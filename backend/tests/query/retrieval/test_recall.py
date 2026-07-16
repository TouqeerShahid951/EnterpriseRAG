# ruff: noqa: F403, F405

from query_retrieval_recall_support import *


def test_definition_query_runs_bounded_recall_expansion_when_top_evidence_is_incomplete() -> (
    None
):
    query = "How does ZTMM define devices?"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=0.0,
    )
    ctx["route_plan"] = definition_plan(query)
    embedder = RecallEmbedder()

    hits = retrieve_candidates(
        ctx, config=FakeConfig(), ollama=embedder, qdrant=FakeDefinitionQdrant()
    )

    assert [item.payload["chunk_id"] for item in hits[:2]] == ["ztmm:98", "ztmm:100"]
    assert hits[0].payload["recall_origin"] == "answer_type_expansion"
    assert embedder.queries[:2] == [query, "ztmm devices definition"]

def test_recall_expansion_preserves_authoritative_exhaustive_provenance() -> None:
    query = "List all terms that define device in all documents"
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
    embedder = RecallEmbedder()

    hits = retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=embedder,
        qdrant=FakeExhaustiveRecallQdrant(),
    )

    assert hits[0].payload["exhaustive_scope_origin"] == "document_class_scope"
    assert hits[0].payload["authorized_scan_complete"] is False
    assert hits[0].payload["recall_origin"] == "answer_type_expansion"

def test_recall_expansion_cannot_escape_resolved_named_document_scope() -> None:
    query = "List all terms that define device in Samsung manual"
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
        ollama=RecallEmbedder(),
        qdrant=FakeNamedRecallQdrant(),
    )

    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert hits[0].payload["exhaustive_scope_origin"] == "document_class_scope"

def test_definition_query_skips_recall_expansion_when_definition_is_already_present() -> (
    None
):
    query = "How does ZTMM define devices?"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=0.0,
    )
    ctx["route_plan"] = definition_plan(query)
    embedder = RecallEmbedder()

    hits = retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=embedder,
        qdrant=FakeDefinitionAlreadyFoundQdrant(),
    )

    assert [item.payload["chunk_id"] for item in hits] == ["ztmm:98"]
    assert embedder.queries == [query]

def test_definition_recall_ignores_generic_overview_cues() -> None:
    query = "How does the Zero Trust Maturity Model define a device?"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=0.0,
    )
    ctx["route_plan"] = definition_plan(query)
    embedder = RecallEmbedder()

    hits = retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=embedder,
        qdrant=FakeDefinitionFalsePositiveQdrant(),
    )

    assert [item.payload["chunk_id"] for item in hits[:2]] == ["ztmm:98", "ztmm:45"]
    assert embedder.queries[:2] == [query, "zero trust device definition"]
