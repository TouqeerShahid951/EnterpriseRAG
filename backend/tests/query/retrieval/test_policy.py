# ruff: noqa: F403, F405

from query_retrieval_scope_support import *


def test_initial_retrieval_state_preserves_artifact_job_query_scope() -> None:
    user = UserContext(
        user_id="user",
        email="user@example.com",
        group_paths=("/admin",),
    )

    ctx = initial_retrieval_state(
        trace_id="trace-1",
        session_id="session-1",
        query="quarterly risk",
        group_path="/finance",
        document_ids=("doc-2", "doc-1"),
        user=user,
        token_budget=4321,
    )

    assert ctx["trace_id"] == "trace-1"
    assert ctx["session_id"] == "session-1"
    assert ctx["request"] == QueryRequest(
        query="quarterly risk",
        session_id="session-1",
        group_path="/finance",
        document_ids=["doc-2", "doc-1"],
    )
    assert ctx["user"] is user
    assert ctx["token_budget"] == 4321
    assert ctx["wall_time_start"] == 0.0

def test_action_target_ignores_trailing_procedure_adjunct() -> None:
    qdrant = FakeSamsungSemanticMissQdrant()
    query = (
        "List all equipment needed to repair a Samsung Galaxy S24 device "
        "using approved procedures"
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

    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert ctx["degraded"] is False

def test_action_target_ignores_under_warranty_adjunct() -> None:
    qdrant = FakeSamsungSemanticMissQdrant()
    query = (
        "List all equipment needed to repair a Samsung Galaxy S24 device under warranty"
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

    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert ctx["degraded"] is False

def test_specific_action_target_beats_generic_manual_clause() -> None:
    qdrant = FakeGenericRepairManualScopeQdrant()
    query = (
        "List all equipment required to repair a Samsung device from the repair manual"
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

def test_action_target_beats_non_document_prepositional_adjunct() -> None:
    qdrant = FakeHospitalPolicyScopeQdrant()
    query = (
        "List all equipment required to repair a Samsung device for use in hospitals"
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

def test_action_target_beats_strong_location_adjunct() -> None:
    qdrant = FakeHomePolicyScopeQdrant()
    query = "List all equipment required to repair a Samsung device from home"
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

    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert ctx["degraded"] is False

def test_bounded_action_target_ignores_unlisted_location_adjunct() -> None:
    qdrant = FakeHomePolicyScopeQdrant()
    query = "List all equipment required to repair a Samsung device at home"
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

    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert ctx["degraded"] is False

def test_document_kind_adjective_cannot_override_action_target() -> None:
    qdrant = FakeManualModeGuideScopeQdrant()
    query = "List all equipment required to repair a Samsung device in manual mode"
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

    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert ctx["degraded"] is False

def test_document_selector_suffix_cannot_become_document_identity() -> None:
    queries = (
        "List all equipment from Samsung repair manual section 3",
        "List all equipment from Samsung repair manual version 2",
    )
    for query in queries:
        qdrant = FakeManualSuffixNotesScopeQdrant()
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

def test_action_target_beats_strong_time_adjunct() -> None:
    qdrant = FakeSamsungSemanticMissQdrant()
    query = "List all equipment required to repair a Samsung device within 30 minutes"
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

    assert {item.payload["doc_id"] for item in hits} == {"samsung"}
    assert ctx["degraded"] is False

def test_generic_action_target_cannot_select_unrelated_named_document() -> None:
    qdrant = FakeDevicePolicyScopeQdrant()
    query = "List all equipment required to repair the device"
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

    assert hits == []
    assert qdrant.authorized_scan_called is True
    assert ctx["degraded_reason"] == "exhaustive_scope_unresolved"

def test_explicit_manual_selector_wins_over_action_target() -> None:
    qdrant = FakeExplicitManualScopeQdrant()
    query = (
        "List all tools to repair a cracked screen and verify them from the "
        "Samsung Operations Manual"
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

    assert {item.payload["doc_id"] for item in hits} == {"samsung-operations"}
    assert ctx["degraded"] is False
