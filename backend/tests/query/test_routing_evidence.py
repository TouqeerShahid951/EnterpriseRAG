from rag.query.qdrant import SearchHit
from rag.query.routing_evidence import inspect_evidence_for_reroute
from rag.query.routing_models import RoutePlan


def hit(point_id: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=0.5,
        payload={
            "doc_id": "doc",
            "chunk_id": point_id,
            "text": "Image description: A soldier is handling ammunition.",
            **payload,
        },
    )


def aggregation_plan() -> RoutePlan:
    return RoutePlan(
        original_query="What are all the soldiers doing in all the documents?",
        resolved_query="What are all the soldiers doing in all the documents?",
        intent="aggregation",
        public_intent="aggregation",
        use_structured_query=True,
        search_mode="structured_first",
        top_k=24,
    )


def test_aggregation_keeps_exhaustive_plain_text_evidence() -> None:
    inspection = inspect_evidence_for_reroute(
        aggregation_plan(),
        [hit("image:0", exhaustive_scope_origin="document_class_scope")],
        reroute_count=0,
    )

    assert inspection.should_reroute is False


def test_aggregation_without_structured_or_scope_evidence_reroutes() -> None:
    inspection = inspect_evidence_for_reroute(
        aggregation_plan(),
        [hit("image:0")],
        reroute_count=0,
    )

    assert inspection.should_reroute is True
    assert inspection.reason == "aggregation_without_structured_evidence"
