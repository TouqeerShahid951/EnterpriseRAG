from time import perf_counter

from rag.auth.context import UserContext
from rag.query.nodes import QueryNodes
from rag.query.qdrant import SearchHit
from rag.query.routing.routing_models import RoutePlan
from rag.query.state import initial_state
from rag.query.schemas import QueryRequest


def hit(point_id: str, *, doc_id: str, doc_title: str, text: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=0.5,
        payload={
            "doc_id": doc_id,
            "chunk_id": point_id,
            "doc_title": doc_title,
            "text": text,
            "page": 1,
            **payload,
        },
    )


def test_verifier_does_not_prune_passing_aggregation_evidence() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list all crimes in all FIRs"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        public_intent="aggregation",
        use_structured_query=True,
        search_mode="structured_first",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit(
            "fir-1:crime",
            doc_id="fir-1",
            doc_title="FIR_01.pdf",
            text="Robbery crime.",
            chunk_type="table_row",
            table_json={"rows": [["crime"], ["robbery"]]},
        ),
        hit(
            "fir-2:crime",
            doc_id="fir-2",
            doc_title="FIR_02.pdf",
            text="Cyber crime.",
            chunk_type="table_row",
            table_json={"rows": [["crime"], ["cyber"]]},
        ),
        hit("manual:1", doc_id="manual", doc_title="Server manual.pdf", text="Server maintenance.", chunk_type="text"),
    ]

    result = QueryNodes.verifier(object.__new__(QueryNodes), ctx)

    assert result["verifier_decision"] == "pass"
    assert [item.payload["doc_id"] for item in result["retrieved_hits"]] == ["fir-1", "fir-2", "manual"]
    assert result["evidence_quality"].in_scope_doc_ids == frozenset({"fir-1", "fir-2"})


def test_verifier_keeps_weak_hits_for_degraded_synthesis() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="employee count at end of year"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="general_rag",
        public_intent="factual_simple",
        top_k=10,
    )
    ctx["retrieved_hits"] = [
        hit(
            "report:page",
            doc_id="report",
            doc_title="Report.pdf",
            text="Unrelated but authorized page text.",
        )
    ]

    result = QueryNodes.verifier(object.__new__(QueryNodes), ctx)

    assert result["verifier_decision"] == "degrade"
    assert result["degraded"] is True
    assert [item.payload["chunk_id"] for item in result["retrieved_hits"]] == ["report:page"]


def test_evidence_builder_keeps_aggregation_rows_exact() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list all crimes in all FIRs"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        public_intent="aggregation",
        chunk_granularity="section",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit(
            "fir-1:crime",
            doc_id="fir-1",
            doc_title="FIR_01.pdf",
            text="Crime: robbery",
            parent_text="A long parent section with unrelated rows.",
            parent_page_start=1,
        )
    ]

    result = QueryNodes.evidence_builder(object.__new__(QueryNodes), ctx)

    assert result["retrieved_hits"][0].payload["text"] == "Crime: robbery"
