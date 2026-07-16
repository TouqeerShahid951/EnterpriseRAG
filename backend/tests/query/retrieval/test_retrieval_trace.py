from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from rag.auth.context import UserContext
from rag.query.nodes import QueryNodes
from rag.query.qdrant import SearchHit
from rag.query.retrieval.retrieval_trace import retrieval_trace_stage
from rag.query.routing.routing_models import RoutePlan
from rag.query.schemas import QueryRequest
from rag.query.state import initial_state


class FakeCrossEncoder:
    def rerank(self, _query: str, passages: list[str]) -> list[float]:
        return [float(len(passages) - index) for index in range(len(passages))]


class SamsungCrossEncoder:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def rerank(self, _query: str, passages: list[str]) -> list[float]:
        self.batch_sizes.append(len(passages))
        return [100.0 if "Safety Goggles" in passage else 0.0 for passage in passages]


class FakeRetrievalService:
    def __init__(self, batches: list[list[SearchHit]]) -> None:
        self.batches = batches

    def retrieve(self, _ctx: object) -> list[SearchHit]:
        return self.batches.pop(0)


def hit(point_id: str, score: float, text: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=score,
        payload={
            "doc_id": "doc",
            "doc_title": "Manual.pdf",
            "chunk_id": point_id,
            "page": 1,
            "text": text,
            **payload,
        },
    )


def test_query_nodes_capture_candidate_fate_across_retrieval_waves() -> None:
    first_wave = [hit("first", 0.2, "unrelated")]
    second_wave = [
        hit("body", 0.9, "alpha answer"),
        hit(
            "table-1",
            0.5,
            "row one",
            chunk_type="table_row",
            table_json={"rows": [["one"]]},
        ),
        hit(
            "table-2",
            0.4,
            "row two",
            chunk_type="table_row",
            table_json={"rows": [["two"]]},
        ),
    ]
    nodes = object.__new__(QueryNodes)
    nodes.retrieval_service = FakeRetrievalService([first_wave, second_wave])
    nodes.config = SimpleNamespace(
        rag_top_k=1,
        rag_reranker_max_candidates=2,
        rag_reranker_cache_dir=None,
    )
    nodes.reranker_model = "test-reranker"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="alpha"),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/space",),
        ),
        started=0.0,
        capture_retrieval_trace=True,
    )
    ctx["route_plan"] = RoutePlan(
        original_query="alpha",
        resolved_query="alpha",
        intent="aggregation",
        public_intent="aggregation",
        use_structured_query=True,
        search_mode="structured_first",
        top_k=1,
    )

    with patch(
        "rag.query.reranker._load_cross_encoder", return_value=FakeCrossEncoder()
    ):
        nodes.abac_retriever(ctx)
        nodes.reranker(ctx)
        nodes.abac_retriever(ctx)
        nodes.reranker(ctx)
        nodes.evidence_builder(ctx)

    stages = ctx["retrieval_trace"]
    assert [stage.attempt for stage in stages if stage.name == "retrieved"] == [0, 1]
    latest = {
        name: next(stage for stage in reversed(stages) if stage.name == name)
        for name in {
            "retrieved",
            "rerank_input",
            "reranked",
            "post_policy",
            "final_evidence",
        }
    }
    assert len(latest["retrieved"].candidates) == 3
    assert len(latest["rerank_input"].candidates) == 2
    assert len(latest["reranked"].candidates) == 1
    assert len(latest["post_policy"].candidates) == 3
    assert len(latest["final_evidence"].candidates) == 1
    assert "text" not in latest["retrieved"].candidates[0].to_row()


def test_trace_keeps_candidate_text_only_until_text_free_serialization() -> None:
    secret = "authorized evidence sentinel"

    stage = retrieval_trace_stage(
        "retrieved",
        [hit("evidence", 0.9, secret, parent_text="unscored parent context")],
        attempt=0,
    )
    candidate = stage.candidates[0]

    assert candidate.evidence_text == secret
    assert secret not in repr(candidate)
    assert secret not in str(candidate.to_row())
    assert {"evidence_text", "text", "parent_text"}.isdisjoint(candidate.to_row())


def test_samsung_style_exhaustive_hits_reach_final_evidence() -> None:
    anchors = (
        "Safety Goggles",
        "Safety Gloves",
        "Safety Mask",
        "Anti-static Wrist Strap",
        "ESD Safe Mat",
        "Ejection Pin",
        "Cross-head Screwdriver",
        "Opening Pick",
        "Opening Tool",
        "Suction Cup",
        "ESD Safe Tweezers",
        "Round Tip Metal Tweezers",
        "Heating Bag",
        "Acrylic Protective Cover for Broken Glass",
    )
    parent_text = "Tools for Disassembly and Assembly\n" + "\n".join(anchors)
    target_positions = {65: 51, 75: 52, 196: 53}
    batch: list[SearchHit] = []
    for index in range(236):
        target = index in target_positions
        page = target_positions.get(index, index // 4 + 1)
        batch.append(
            hit(
                f"chunk-{index:03d}",
                1.0 - index / 1000,
                (
                    anchors[list(target_positions).index(index)]
                    if target
                    else (
                        "Refer to Tools for Disassembly and Assembly."
                        if index == 0
                        else f"generic passage {index}"
                    )
                ),
                page=page,
                parent_page_start=51 if target else page,
                parent_page_end=53 if target else page,
                parent_section_id="tools" if target else f"section-{index}",
                parent_chunk_id="tools-parent" if target else f"parent-{index}",
                parent_text=parent_text
                if target
                else f"generic parent passage {index}",
                section_title=(
                    "Tools for Disassembly and Assembly"
                    if target
                    else f"Generic Section {index}"
                ),
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
        )

    nodes = object.__new__(QueryNodes)
    nodes.retrieval_service = FakeRetrievalService([batch])
    nodes.config = SimpleNamespace(
        rag_top_k=24,
        rag_reranker_max_candidates=40,
        rag_reranker_cache_dir=None,
    )
    nodes.reranker_model = "test-reranker"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(
            query="Give me a list of all the equipment required to repair a Samsung device. Do not miss any."
        ),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/space",),
        ),
        started=0.0,
        capture_retrieval_trace=True,
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        public_intent="aggregation",
        use_structured_query=True,
        search_mode="structured_first",
        chunk_granularity="section",
        top_k=24,
    )
    model = SamsungCrossEncoder()

    with patch("rag.query.reranker._load_cross_encoder", return_value=model):
        nodes.abac_retriever(ctx)
        nodes.reranker(ctx)
        nodes.evidence_builder(ctx)

    rerank_input = next(
        stage
        for stage in reversed(ctx["retrieval_trace"])
        if stage.name == "rerank_input"
    )
    reranked = next(
        stage
        for stage in reversed(ctx["retrieval_trace"])
        if stage.name == "reranked"
    )
    final_evidence = next(
        stage
        for stage in reversed(ctx["retrieval_trace"])
        if stage.name == "final_evidence"
    )
    target_input = [
        item
        for item in rerank_input.candidates
        if item.chunk_id in {"chunk-065", "chunk-075", "chunk-196"}
    ]
    assert {item.page for item in target_input} == {51, 52, 53}
    assert any(
        item.page_start == 51
        and item.page_end == 53
        and all(anchor in item.evidence_text for anchor in anchors)
        for item in target_input
    )
    assert any(
        item.page_start == 51
        and item.page_end == 53
        and all(anchor in item.evidence_text for anchor in anchors)
        for item in reranked.candidates
    )
    assert any(
        item.page_start == 51 and item.page_end == 53
        for item in final_evidence.candidates
    )
    final_text = "\n".join(
        str(item.payload.get("text", "")) for item in ctx["retrieved_hits"]
    )
    assert all(anchor in final_text for anchor in anchors)
    assert all(size <= 32 for size in model.batch_sizes)
    assert ctx["degraded"] is True
    assert ctx["degraded_reason"] == "exhaustive_final_evidence_coverage_partial"
    assert ctx["exhaustive_coverage"]["evidence_status"] == "partial"
    assert "semantic_scope_unresolved" in ctx["exhaustive_coverage"]["reasons"]
    assert all("text" not in item.to_row() for item in rerank_input.candidates)


def test_exhaustive_budget_loss_is_reported_as_partial() -> None:
    nodes = object.__new__(QueryNodes)
    nodes.config = SimpleNamespace(rag_top_k=2)
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list every section"),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/space",),
        ),
        started=0.0,
        capture_retrieval_trace=True,
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        public_intent="aggregation",
        chunk_granularity="section",
        top_k=2,
    )
    ctx["token_budget"] = 5
    ctx["retrieved_hits"] = [
        hit(
            "section-a",
            1.0,
            "A",
            parent_text="A" * 100,
            parent_page_start=1,
            exhaustive_coverage_unit_id="unit-a",
            coverage_role="exhaustive_section_representative",
        ),
        hit(
            "section-b",
            0.9,
            "B",
            parent_text="B" * 100,
            parent_page_start=2,
            exhaustive_coverage_unit_id="unit-b",
            coverage_role="exhaustive_section_representative",
        ),
    ]

    nodes.evidence_builder(ctx)

    assert ctx["retrieved_hits"] == []
    assert ctx["degraded"] is True
    assert ctx["degraded_reason"] == "exhaustive_final_evidence_coverage_partial"
