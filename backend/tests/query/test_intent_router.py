from rag.core.config import Settings
from rag.query.intent_router import route_query


class FailingRouteVerifier:
    def verify_route(self, **kwargs):
        raise AssertionError("deterministic exhaustive summary route should not call verifier")


def test_default_top_k_is_ten() -> None:
    assert Settings.model_fields["rag_top_k"].default == 10


def test_exhaustive_fir_summary_routes_to_aggregation_without_verifier() -> None:
    plan, _signals = route_query(
        "summarize all the crimes in FIRs",
        turns=[],
        base_top_k=10,
        llm_verifier=FailingRouteVerifier(),
        verifier_enabled=True,
    )

    assert plan.intent == "aggregation"
    assert plan.public_intent == "aggregation"
    assert plan.retrieval_strategy == "structured_table_metadata_first"
    assert plan.search_mode == "structured_first"
    assert plan.use_structured_query is True
    assert plan.top_k == 24
    assert any(hit.signal == "exhaustive_summary_document_class" for hit in plan.rule_hits)


def test_single_fir_summary_stays_on_summary_route() -> None:
    plan, _signals = route_query(
        "summarize FIR_04_cybercrime.pdf",
        turns=[],
        base_top_k=10,
        verifier_enabled=False,
    )

    assert plan.intent == "summarization"
    assert plan.retrieval_strategy == "section_or_document_summary"
    assert plan.use_structured_query is False
    assert plan.top_k == 10
