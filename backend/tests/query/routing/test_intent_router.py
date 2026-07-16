from rag.core.config import Settings
from rag.query.http import ServiceRequestError
from rag.query.routing.intent_router import route_query
from rag.query.routing.routing_signals import extract_query_signals
from rag.query.routing.routing_verifier import build_route_verifier_prompt


class FailingRouteVerifier:
    def verify_route(self, **kwargs):
        raise AssertionError("deterministic exhaustive summary route should not call verifier")


class ServiceErrorRouteVerifier:
    def verify_route(self, **kwargs):
        raise ServiceRequestError("vllm", "context length exceeded", 400)


def test_default_top_k_is_ten() -> None:
    assert Settings.model_fields["rag_top_k"].default == 10
    assert Settings.model_fields["rag_query_planner_enabled"].default is True


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


def test_theme_queries_route_to_graphrag_global() -> None:
    plan, _signals = route_query(
        "What are the major themes and recurring risks across all documents?",
        turns=[],
        base_top_k=10,
        verifier_enabled=False,
    )

    assert plan.intent == "graphrag_global"
    assert plan.public_intent == "aggregation"
    assert plan.retrieval_strategy == "graphrag_global"
    assert plan.search_mode == "hybrid"
    assert plan.use_reranker is False
    assert plan.use_structured_query is False


def test_exact_collection_lists_stay_on_aggregation_route() -> None:
    plan, _signals = route_query(
        "list all risks across all documents",
        turns=[],
        base_top_k=10,
        verifier_enabled=False,
    )

    assert plan.intent == "aggregation"
    assert plan.retrieval_strategy == "structured_table_metadata_first"
    assert plan.use_structured_query is True


def test_samsung_exhaustive_typo_query_routes_without_verifier() -> None:
    plan, _signals = route_query(
        "Give me a list of all the equipments required to repair a samsung. Dont skip or miss any.",
        turns=[],
        base_top_k=10,
        llm_verifier=FailingRouteVerifier(),
        verifier_enabled=True,
    )

    assert plan.intent == "aggregation"
    assert plan.retrieval_strategy == "structured_table_metadata_first"
    assert plan.search_mode == "structured_first"
    assert plan.use_structured_query is True
    assert plan.top_k == 24


def test_most_assigned_cases_routes_to_aggregation() -> None:
    plan, _signals = route_query(
        "Which officer has the most assigned cases?",
        turns=[],
        base_top_k=10,
        verifier_enabled=False,
    )

    assert plan.intent == "aggregation"
    assert plan.retrieval_strategy == "structured_table_metadata_first"
    assert plan.use_structured_query is True


def test_query_planner_can_be_disabled_globally() -> None:
    plan, _signals = route_query(
        "compare FIR_04_cybercrime.pdf and FIR_05_narcotics.pdf",
        turns=[],
        base_top_k=10,
        verifier_enabled=False,
        query_planner_enabled=False,
    )

    assert plan.intent == "comparison"
    assert plan.use_query_planner is False


def test_route_verifier_prompt_trims_oversized_queries() -> None:
    query = "compare all documents. " + "preserve exact evidence and table values. " * 1000
    signals = extract_query_signals(query, [])
    prompt = build_route_verifier_prompt(signals, {"aggregation": 0.7, "comparison": 0.6})

    assert len(prompt) < 7000
    assert "chars omitted" in prompt
    assert "Resolved query:\n<same as original query>" in prompt


def test_route_verifier_service_error_falls_back() -> None:
    plan, _signals = route_query(
        "compare every document",
        turns=[],
        base_top_k=10,
        llm_verifier=ServiceErrorRouteVerifier(),
        verifier_enabled=True,
    )

    assert plan.route_method == "fallback"
    assert any(penalty.reason == "llm_verifier_failed" for penalty in plan.penalties)
