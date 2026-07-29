from types import SimpleNamespace
from typing import cast

import pytest

from rag.query.answering.synthesis import synthesis_profile_for_plan
from rag.query.nodes.node_support import (
    _apply_route_plan,
    _should_promote_parent_context,
)
from rag.query.nodes.retrieval_nodes import (
    _final_evidence_budget,
    _reranker_candidate_limit,
)
from rag.query.routing.routing_models import RoutePlan
from rag.query.state import QueryContext


def _plan(**updates: object) -> RoutePlan:
    values = {
        "original_query": "query",
        "resolved_query": "resolved query",
        "intent": "general_rag",
    }
    values.update(updates)
    return RoutePlan(**values)  # type: ignore[arg-type]


def test_route_application_uses_typed_subqueries_and_temporal_scope() -> None:
    ctx = cast(QueryContext, {})
    _apply_route_plan(
        ctx,
        _plan(
            sub_queries=("first", "second"),
            temporal_scope="historical",
        ),
    )

    assert ctx["sub_queries"] == ["first", "second"]
    assert ctx["is_current_only"] is False


def test_parent_promotion_uses_capability_instead_of_legacy_intent() -> None:
    plan = _plan(
        intent="factual_simple",
        capabilities=("general_search", "document_search"),
        chunk_granularity="section",
    )

    assert _should_promote_parent_context(plan) is True


def test_factual_lookup_uses_smaller_reranker_budget() -> None:
    assert _reranker_candidate_limit(_plan(top_k=10), 40) == 12
    assert _reranker_candidate_limit(_plan(top_k=24), 40) == 12


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"response_mode": "summary"}, 16),
        ({"response_mode": "comparison"}, 20),
        ({"capabilities": ("general_search", "decomposed_search")}, 20),
        ({"capabilities": ("general_search", "structured_query")}, 24),
        ({"coverage": "exhaustive"}, 24),
    ],
)
def test_route_uses_bounded_reranker_budget(
    updates: dict[str, object], expected: int
) -> None:
    assert _reranker_candidate_limit(_plan(**updates), 40) == expected


def test_operator_reranker_limit_remains_the_hard_ceiling() -> None:
    assert (
        _reranker_candidate_limit(
            _plan(capabilities=("general_search", "structured_query")),
            10,
        )
        == 10
    )


def test_uncertain_implicit_hybrid_route_widens_reranker_budget() -> None:
    source_decision = SimpleNamespace(
        explicit=False,
        resolved_mode="hybrid",
        routing_confidence=0.7,
    )

    assert (
        _reranker_candidate_limit(
            _plan(),
            40,
            source_decision=source_decision,
        )
        == 20
    )
    assert (
        _reranker_candidate_limit(
            _plan(),
            16,
            source_decision=source_decision,
        )
        == 16
    )


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({}, (4, 3_000)),
        ({"response_mode": "explanation"}, (4, 4_000)),
        ({"response_mode": "summary"}, (6, 5_000)),
        ({"response_mode": "comparison"}, (6, 6_000)),
        ({"capabilities": ("general_search", "decomposed_search")}, (8, 6_000)),
        ({"capabilities": ("general_search", "structured_query")}, (8, 6_000)),
        ({"coverage": "exhaustive"}, (12, 12_000)),
    ],
)
def test_route_uses_independent_final_evidence_budget(
    updates: dict[str, object], expected: tuple[int, int]
) -> None:
    assert (
        _final_evidence_budget(
            _plan(top_k=24, **updates),
            configured_limit=24,
            configured_token_budget=24_000,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"response_mode": "summary"}, "summarization"),
        ({"response_mode": "comparison", "temporal_scope": "all"}, "temporal_comparison"),
        ({"capabilities": ("general_search", "document_navigation")}, "document_navigation"),
        (
            {
                "capabilities": ("general_search", "structured_query"),
                "coverage": "exhaustive",
            },
            "aggregation",
        ),
    ],
)
def test_synthesis_profile_uses_typed_plan_fields(
    updates: dict[str, object], expected: str
) -> None:
    assert synthesis_profile_for_plan(_plan(**updates)) == expected
