import pytest

from rag.query.retrieval.retrieval_plans import retrieval_settings_for


def _settings(
    capabilities=(),
    *,
    response_mode="lookup",
    scope="local",
    coverage="focused",
    temporal_scope="current",
    query="find the requested attribute",
):
    return retrieval_settings_for(
        capabilities,
        response_mode=response_mode,
        scope=scope,
        coverage=coverage,
        temporal_scope=temporal_scope,
        query=query,
        base_top_k=4,
    )


def test_empty_capability_plan_uses_safe_general_search() -> None:
    settings = _settings()

    assert settings == {
        "needs_retrieval": True,
        "retrieval_strategy": "hybrid_reranked",
        "search_mode": "hybrid",
        "use_query_planner": False,
        "use_reranker": True,
        "use_temporal_filter": False,
        "use_conflict_checker": False,
        "use_structured_query": False,
        "chunk_granularity": "medium",
        "top_k": 4,
        "filters": {},
        "allow_abstain": True,
        "risk_level": "low",
    }


def test_capabilities_combine_without_losing_specialized_execution_flags() -> None:
    settings = _settings(("general_search", "structured_query", "decomposed_search"))

    assert settings["retrieval_strategy"] == "structured_table_metadata_first"
    assert settings["search_mode"] == "structured_first"
    assert settings["use_structured_query"] is True
    assert settings["use_query_planner"] is True
    assert settings["use_reranker"] is True
    assert settings["chunk_granularity"] == "section"
    assert settings["top_k"] == 24
    assert settings["risk_level"] == "high"


def test_live_sql_is_independent_from_document_table_execution() -> None:
    settings = _settings(("general_search", "live_sql"))

    assert settings["retrieval_strategy"] == "live_sql_hybrid"
    assert settings["search_mode"] == "hybrid"
    assert settings["use_structured_query"] is False
    assert settings["chunk_granularity"] == "medium"
    assert settings["top_k"] == 4
    assert settings["risk_level"] == "high"


def test_document_coverage_is_derived_from_scope_not_query_vocabulary() -> None:
    first = _settings(
        ("document_search",), scope="corpus", coverage="exhaustive", query="alpha"
    )
    second = _settings(
        ("document_search",), scope="corpus", coverage="exhaustive", query="beta"
    )

    assert first == second
    assert first["retrieval_strategy"] == "section_or_document_summary"
    assert first["chunk_granularity"] == "document"
    assert first["top_k"] == 24
    assert first["risk_level"] == "high"


def test_temporal_scope_and_exact_date_compile_to_filters() -> None:
    historical = _settings(temporal_scope="historical")
    all_versions = _settings(temporal_scope="all")
    as_of = _settings(temporal_scope="as_of", query="state at 2024-02")

    assert historical["use_temporal_filter"] is True
    assert historical["filters"] == {}
    assert all_versions["use_temporal_filter"] is False
    assert as_of["use_temporal_filter"] is True
    assert as_of["filters"] == {"target_date": "2024-02-29"}


def test_conflict_response_enables_checker_without_changing_capabilities() -> None:
    settings = _settings(response_mode="conflict_analysis")

    assert settings["retrieval_strategy"] == "competing_claims_hybrid"
    assert settings["use_conflict_checker"] is True
    assert settings["top_k"] == 8
    assert settings["risk_level"] == "high"


def test_invalid_internal_capability_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="Unsupported retrieval capabilities: magic"):
        _settings(("magic",))
