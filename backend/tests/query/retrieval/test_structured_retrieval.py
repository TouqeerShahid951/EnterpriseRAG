# ruff: noqa: F403, F405

from query_retrieval_scope_support import *
from rag.query.retrieval.retrieval_structured import _should_use_structured_path


def test_structured_expansion_is_selected_from_retrieved_metadata() -> None:
    plan = definition_plan("Find Touqeer's reference number")
    plain = hit(
        "offer:plain",
        doc_id="offer",
        doc_title="Offer letter",
        text="Touqeer accepted the offer.",
    )
    structured = hit(
        "offer:reference",
        doc_id="offer",
        doc_title="Offer letter",
        text="Reference No: CA/PK/HR/004",
        structured_kind="kv_record",
        structured_field_names=["Reference No"],
    )

    assert _should_use_structured_path(plan.resolved_query, [plain], plan) is False
    assert _should_use_structured_path(plan.resolved_query, [structured], plan) is True


def test_retrieval_records_embedding_vector_and_table_timings() -> None:
    class StructuredQdrant(FakeQdrant):
        def search(self, _vector, *, limit, qdrant_filter):
            _ = limit, qdrant_filter
            return [
                hit(
                    "offer:reference",
                    doc_id="offer",
                    doc_title="Offer letter",
                    text="Touqeer | CA/PK/HR/004",
                    chunk_type="table_row",
                    structured_kind="table_row",
                    structured_field_names=["Candidate", "Reference No"],
                    table_title="Offer details",
                )
            ]

        def retrieve_table_rows(self, **_kwargs):
            return []

    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="Find Touqeer's reference number"),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=0.0,
    )
    ctx["route_plan"] = definition_plan(ctx["request"].query)

    retrieve_candidates(
        ctx,
        config=FakeConfig(),
        ollama=FakeEmbedder(),
        qdrant=StructuredQdrant(),
    )

    assert set(ctx["retrieval_phase_timings_ms"]) == {
        "embeddings",
        "vector_search",
        "table_expansion",
    }


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
