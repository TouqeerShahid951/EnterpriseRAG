from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from rag.auth.context import UserContext
from rag.query.nodes import QueryNodes
from rag.query.nodes.retrieval_nodes import (
    _capability_origins,
    _merge_capability_hits,
    _preserve_capability_coverage,
)
from rag.query.qdrant import SearchHit
from rag.query.reranking.models import RerankResult
from rag.query.routing.routing_models import RoutePlan
from rag.query.schemas import QueryRequest
from rag.query.sources.source_resolution import SourceDecision
from rag.query.state import initial_state


def _hit(point_id: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=0.5,
        payload={
            "doc_id": point_id,
            "chunk_id": point_id,
            "doc_title": f"{point_id}.pdf",
            "text": point_id,
            **payload,
        },
    )


def _scored(hit: SearchHit, score: float) -> SearchHit:
    return SearchHit(
        point_id=hit.point_id,
        score=hit.score,
        payload={
            **hit.payload,
            "_rerank_score": score,
            "_rerank_status": "scored",
        },
    )


def test_reranker_keeps_general_and_each_available_specialist_within_top_k() -> None:
    plan = RoutePlan(
        original_query="Find the answer",
        resolved_query="Find the answer",
        intent="general_rag",
        capabilities=(
            "general_search",
            "structured_query",
            "live_sql",
            "document_search",
            "global_graph",
        ),
        top_k=24,
    )
    general = [_hit(f"general-{index}") for index in range(24)]
    structured = _hit(
        "structured",
        chunk_type="table_row",
        table_json={"rows": [["reference", "OL-42"]]},
    )
    document = _hit(
        "document",
        exhaustive_scope_origin="document_class_scope",
    )
    live_sql = _hit(
        "live-sql",
        source_type="connector_live_sql_database_scope",
        structured_kind="kv_record",
    )
    graph = _hit("graph")
    candidates = _merge_capability_hits(
        [*general, structured, live_sql, document],
        [graph],
        capabilities=plan.capabilities,
    )
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=plan.original_query),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/space",),
        ),
        started=0.0,
    )
    ctx["route_plan"] = plan
    ctx["retrieved_hits"] = candidates
    nodes = object.__new__(QueryNodes)
    nodes.config = SimpleNamespace(
        rag_top_k=24,
        rag_reranker_max_candidates=40,
        rag_reranker_cache_dir=None,
    )
    nodes.reranker_model = "test-reranker"
    ranked_candidates = tuple(
        _scored(hit, float(len(candidates) - index))
        for index, hit in enumerate(candidates)
    )

    with patch(
        "rag.query.nodes.retrieval_nodes.rerank_hits_with_result",
        return_value=RerankResult(
            candidates=tuple(candidates),
            ranked_hits=tuple(
                hit
                for hit in ranked_candidates
                if _capability_origins(hit) == ("general_search",)
            )[: plan.top_k],
            ranked_candidates=ranked_candidates,
        ),
    ):
        nodes.reranker(ctx)

    assert len(ctx["retrieved_hits"]) == plan.top_k
    retained = {
        capability
        for hit in ctx["retrieved_hits"][:10]
        for capability in _capability_origins(hit)
    }
    assert retained == set(plan.capabilities)
    assert any(
        _capability_origins(hit) == ("general_search",) for hit in ctx["retrieved_hits"]
    )
    assert all(
        hit.payload.get("_rerank_status") == "scored"
        for hit in ctx["retrieved_hits"]
    )


def test_duplicate_general_and_graph_hit_keeps_both_capability_origins() -> None:
    general = _hit("same")
    graph = _hit("graph-copy", doc_id="same", chunk_id="same")

    merged = _merge_capability_hits(
        [general],
        [graph],
        capabilities=("general_search", "global_graph"),
    )

    assert len(merged) == 1
    assert set(_capability_origins(merged[0])) == {
        "general_search",
        "global_graph",
    }


def test_single_capability_ranked_evidence_is_not_displaced_by_a_reserve() -> None:
    plan = RoutePlan(
        original_query="Find the answer",
        resolved_query="Find the answer",
        intent="general_rag",
        capabilities=("general_search",),
        top_k=2,
    )
    reserve = _hit("retrieval-head", _retrieval_capabilities=["general_search"])
    answer = _hit("answer", _retrieval_capabilities=["general_search"])
    supporting = _hit("supporting", _retrieval_capabilities=["general_search"])

    result = _preserve_capability_coverage(
        [reserve, answer, supporting],
        [answer, supporting],
        plan=plan,
    )

    assert [hit.point_id for hit in result] == ["answer", "supporting"]


def test_multi_capability_route_reserves_a_pure_general_result() -> None:
    plan = RoutePlan(
        original_query="Find the answer",
        resolved_query="Find the answer",
        intent="general_rag",
        capabilities=("general_search", "structured_query"),
        top_k=2,
    )
    general = _hit("general", _retrieval_capabilities=["general_search"])
    structured_one = _hit(
        "structured-1",
        _retrieval_capabilities=["general_search", "structured_query"],
    )
    structured_two = _hit(
        "structured-2",
        _retrieval_capabilities=["general_search", "structured_query"],
    )

    result = _preserve_capability_coverage(
        [general, structured_one, structured_two],
        [structured_one, structured_two],
        plan=plan,
    )

    assert [hit.point_id for hit in result] == ["structured-1", "general"]


def test_corpus_expansion_reuses_graph_state_without_graph_vector_rerun() -> None:
    query = "Compare the policy with the live case status"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/space",),
        ),
        started=0.0,
    )
    ctx["route_plan"] = RoutePlan(
        original_query=query,
        resolved_query=query,
        intent="multi_hop",
        capabilities=("general_search", "global_graph", "live_sql"),
    )
    ctx["source_decision"] = SourceDecision(
        requested_mode="auto",
        resolved_mode="hybrid",
        semantic_query=query,
        explicit=False,
        reason="auto_corpus_first_corpus_preferred:evidence_expansion",
        preferred_source="corpus",
    )
    ctx["source_expansion_from"] = "corpus_first"
    saved_communities = [{"id": "community-1"}]
    ctx["graphrag_communities"] = saved_communities
    merged_hit = _hit("saved-corpus-plus-live")
    nodes = object.__new__(QueryNodes)
    nodes.retrieval_service = SimpleNamespace(
        retrieve=lambda _ctx: [merged_hit],
    )

    with patch("rag.query.nodes.retrieval_nodes.GraphRAGRetriever") as graph_retriever:
        result = nodes.abac_retriever(ctx)

    graph_retriever.assert_not_called()
    assert result["graphrag_communities"] is saved_communities
    assert [hit.point_id for hit in result["retrieved_hits"]] == [
        "saved-corpus-plus-live"
    ]
