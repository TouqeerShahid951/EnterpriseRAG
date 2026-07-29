import json
from dataclasses import replace
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rag.auth.context import UserContext
from rag.query.nodes import QueryNodes
from rag.query.qdrant import SearchHit
from rag.query.routing.routing_models import RetrievalCapability, RoutePlan
from rag.query.schemas import QueryRequest
from rag.query.sources.source_resolution import SourceDecision
from rag.query.state import QueryContext, initial_state


class FakeInference:
    def __init__(self, result: str | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def generate_json(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class AnswerCrossEncoder:
    def rerank(self, _query: str, passages: list[str]) -> list[float]:
        return [1.0 if "OL-2026-041" in passage else 0.0 for passage in passages]


def _result(
    *,
    relevance: str,
    sufficiency: str,
    supported: list[str],
    missing: list[str],
    action: str,
) -> str:
    return json.dumps(
        {
            "relevance": relevance,
            "sufficiency": sufficiency,
            "supported_aspects": supported,
            "missing_aspects": missing,
            "action": action,
        }
    )


def _hit(
    text: str = "Offer letter reference number OL-2026-041 for Touqeer.",
) -> SearchHit:
    return SearchHit(
        point_id="offer-letter:1",
        score=0.9,
        payload={
            "doc_id": "offer-letter",
            "chunk_id": "offer-letter:1",
            "doc_title": "Offer Letter.pdf",
            "text": text,
            "page": 1,
        },
    )


def _structured_hit() -> SearchHit:
    return SearchHit(
        point_id="offer-letter:1",
        score=0.9,
        payload={
            "doc_id": "offer-letter",
            "chunk_id": "offer-letter:1",
            "doc_title": "Offer Letter.pdf",
            "text": "Offer letter reference number OL-2026-041 for Touqeer.",
            "page": 1,
            "_rerank_score": 0.9,
            "structured_kind": "kv_record",
            "structured_fields": [
                {"label": "Reference number", "value": "OL-2026-041"},
                {"label": "Name", "value": "Touqeer"},
            ],
        },
    )


def _mismatched_structured_hit() -> SearchHit:
    return SearchHit(
        point_id="offer-letter:wrong",
        score=0.9,
        payload={
            "doc_id": "offer-letter-index",
            "chunk_id": "offer-letter:wrong",
            "doc_title": "Touqeer Offer Letter Index.pdf",
            "text": "Offer letter reference number WRONG-999 for Someone Else.",
            "page": 1,
            "_rerank_score": 0.9,
            "structured_kind": "kv_record",
            "structured_fields": [
                {"label": "Reference number", "value": "WRONG-999"},
                {"label": "Recipient", "value": "Someone Else"},
            ],
        },
    )


def _context(
    *,
    capabilities: tuple[RetrievalCapability, ...] = ("general_search",),
) -> QueryContext:
    query = "What is the reference number of the offer letter for Touqeer?"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=query,
        resolved_query=query,
        intent="general_rag",
        capabilities=capabilities,
        route_method="llm_planner",
    )
    ctx["retrieved_hits"] = [_hit()]
    return ctx


def _nodes(
    result: str | Exception,
    *,
    live_sql_enabled: bool = True,
) -> tuple[QueryNodes, FakeInference]:
    inference = FakeInference(result)
    nodes = object.__new__(QueryNodes)
    nodes.ollama = inference
    nodes.reasoning_model = "evidence-judge"
    nodes.evidence_gate_policy = "always"
    nodes.config = SimpleNamespace(
        rag_query_rewrite_llm_enabled=False,
        rag_retrieval_max_retries=1,
        rag_top_k=4,
        rag_reranker_max_candidates=40,
        rag_reranker_cache_dir=None,
        connector_live_sql_enabled=live_sql_enabled,
    )
    nodes.reranker_model = "test-reranker"
    return nodes, inference


def test_never_policy_skips_semantic_evidence_judge() -> None:
    nodes, inference = _nodes(RuntimeError("must not run"))
    nodes.evidence_gate_policy = "never"
    ctx = _context()
    ctx["verifier_decision"] = "pass"
    original_hits = list(ctx["retrieved_hits"])

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "pass"
    assert result["retrieved_hits"] == original_hits
    assert result["execution_modes"]["evidence_gate"] == "skipped"
    assert result["execution_details"]["evidence_gate"] == "policy_disabled"
    assert "evidence_sufficiency" not in result
    assert inference.calls == []


def test_adaptive_policy_skips_judge_for_strong_low_risk_lookup() -> None:
    nodes, inference = _nodes(RuntimeError("must not run"))
    nodes.evidence_gate_policy = "adaptive"

    result = nodes.evidence_gate(_context())

    assert result["verifier_decision"] == "pass"
    assert result["evidence_sufficiency"].evaluator_status == "not_needed"
    assert result["execution_modes"]["evidence_gate"] == "deterministic"
    assert inference.calls == []


@pytest.mark.parametrize(
    ("score", "expected_mode", "expected_calls"),
    [(0.55, "deterministic", 0), (0.549, "ai_assisted", 1)],
)
def test_adaptive_evidence_threshold_is_conservative(
    score: float,
    expected_mode: str,
    expected_calls: int,
) -> None:
    nodes, inference = _nodes(
        _result(
            relevance="relevant",
            sufficiency="sufficient",
            supported=["offer letter reference number"],
            missing=[],
            action="answer",
        )
    )
    nodes.evidence_gate_policy = "adaptive"
    ctx = _context()
    ctx["retrieved_hits"] = [replace(_hit(), score=score)]

    result = nodes.evidence_gate(ctx)

    assert result["execution_modes"]["evidence_gate"] == expected_mode
    assert len(inference.calls) == expected_calls


@pytest.mark.parametrize("risk_level", ["medium", "high"])
def test_adaptive_policy_keeps_judge_for_higher_risk_lookup(
    risk_level: str,
) -> None:
    nodes, inference = _nodes(
        _result(
            relevance="relevant",
            sufficiency="sufficient",
            supported=["offer letter reference number"],
            missing=[],
            action="answer",
        )
    )
    nodes.evidence_gate_policy = "adaptive"
    ctx = _context()
    ctx["route_plan"] = replace(ctx["route_plan"], risk_level=risk_level)

    result = nodes.evidence_gate(ctx)

    assert result["evidence_sufficiency"].evaluator_status == "checked"
    assert result["execution_modes"]["evidence_gate"] == "ai_assisted"
    assert len(inference.calls) == 1


def test_adaptive_policy_keeps_judge_for_weak_evidence() -> None:
    nodes, inference = _nodes(
        _result(
            relevance="mixed",
            sufficiency="partial",
            supported=["recipient"],
            missing=["offer letter reference number"],
            action="partial",
        )
    )
    nodes.evidence_gate_policy = "adaptive"
    ctx = _context()
    weak_hit = _hit("Touqeer is named in this document.")
    weak_hit.payload["doc_title"] = "Miscellaneous.pdf"
    ctx["retrieved_hits"] = [weak_hit]

    result = nodes.evidence_gate(ctx)

    assert result["evidence_sufficiency"].evaluator_status == "checked"
    assert len(inference.calls) == 1


def _corpus_first_context(*, live_sql_planned: bool = True) -> QueryContext:
    capabilities: tuple[RetrievalCapability, ...] = (
        ("general_search", "live_sql") if live_sql_planned else ("general_search",)
    )
    ctx = _context(capabilities=capabilities)
    ctx["source_decision"] = SourceDecision(
        requested_mode="auto",
        resolved_mode="corpus_first",
        semantic_query=ctx["request"].query,
        explicit=False,
        reason="auto_corpus_first_corpus_preferred",
        preferred_source="corpus",
        routing_confidence=0.9,
    )
    return ctx


def test_sufficient_evidence_passes_with_hits_intact() -> None:
    nodes, inference = _nodes(
        _result(
            relevance="relevant",
            sufficiency="sufficient",
            supported=["offer letter reference number"],
            missing=[],
            action="answer",
        )
    )
    ctx = _context()
    original_hits = list(ctx["retrieved_hits"])

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "pass"
    assert result["retrieved_hits"] == original_hits
    assert result["degraded"] is False
    assert result["evidence_sufficiency"].evaluator_status == "checked"
    assert result["execution_modes"]["evidence_gate"] == "ai_assisted"
    assert inference.calls[0]["model"] == "evidence-judge"


def test_reranker_defers_semantic_judgment_until_evidence_gate() -> None:
    nodes, inference = _nodes(
        _result(
            relevance="relevant",
            sufficiency="sufficient",
            supported=["offer letter reference number"],
            missing=[],
            action="answer",
        )
    )
    ctx = _context()
    ctx["retrieved_hits"] = [
        _hit(),
        *[
            SearchHit(
                point_id=f"generic-{index}",
                score=0.8 - index / 100,
                payload={
                    "doc_id": f"generic-{index}",
                    "chunk_id": f"generic-{index}",
                    "doc_title": f"Generic {index}.pdf",
                    "text": f"Generic passage {index}",
                    "page": 1,
                },
            )
            for index in range(39)
        ],
    ]
    with patch(
        "rag.query.reranker._load_cross_encoder",
        return_value=AnswerCrossEncoder(),
    ):
        nodes.reranker(ctx)
        assert inference.calls == []
        nodes.evidence_builder(ctx)
        result = nodes.evidence_gate(ctx)

    assert len(inference.calls) == 1
    assert result["verifier_decision"] == "pass"
    assert result["execution_modes"]["reranker"] == "deterministic"


def test_mismatched_structured_lookup_does_not_bypass_semantic_judge() -> None:
    nodes, inference = _nodes(
        _result(
            relevance="irrelevant",
            sufficiency="insufficient",
            supported=[],
            missing=["The retrieved record belongs to a different recipient."],
            action="abstain",
        )
    )
    ctx = _context()
    ctx["retrieved_hits"] = [_mismatched_structured_hit()]

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "degrade"
    assert result["evidence_sufficiency"].evaluator_status == "checked"
    assert result["execution_modes"]["evidence_gate"] == "ai_assisted"
    assert len(inference.calls) == 1


def test_specialized_route_keeps_evidence_llm_for_structured_hit() -> None:
    nodes, inference = _nodes(
        _result(
            relevance="relevant",
            sufficiency="sufficient",
            supported=["offer letter reference number"],
            missing=[],
            action="answer",
        )
    )
    ctx = _context()
    ctx["route_plan"] = replace(
        ctx["route_plan"],
        capabilities=("general_search", "live_sql"),
    )
    ctx["retrieved_hits"] = [_structured_hit()]

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "pass"
    assert result["evidence_sufficiency"].evaluator_status == "checked"
    assert len(inference.calls) == 1


def test_sufficient_corpus_evidence_stops_without_live_expansion() -> None:
    nodes, _ = _nodes(
        _result(
            relevance="relevant",
            sufficiency="sufficient",
            supported=["offer letter reference number"],
            missing=[],
            action="answer",
        )
    )
    ctx = _corpus_first_context()
    original_hits = list(ctx["retrieved_hits"])

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "pass"
    assert result["retrieved_hits"] == original_hits
    assert result["retry_count"] == 0
    assert result["source_decision"].resolved_mode == "corpus_first"
    assert "source_expansion_from" not in result


@pytest.mark.parametrize(
    "judge_result",
    [
        _result(
            relevance="relevant",
            sufficiency="partial",
            supported=["Touqeer is the recipient"],
            missing=["offer letter reference number"],
            action="partial",
        ),
        _result(
            relevance="irrelevant",
            sufficiency="insufficient",
            supported=[],
            missing=["offer letter reference number"],
            action="abstain",
        ),
        RuntimeError("judge unavailable"),
    ],
    ids=["partial", "insufficient", "evaluator-unavailable"],
)
def test_non_decisive_corpus_evidence_expands_once_to_live_sql(
    judge_result: str | Exception,
) -> None:
    nodes, _ = _nodes(judge_result)
    ctx = _corpus_first_context()
    primary_hits = list(ctx["retrieved_hits"])

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "retry"
    assert result["retry_count"] == 1
    assert result["retrieved_hits"] == []
    assert result["source_primary_hits"] == primary_hits
    assert result["source_expansion_from"] == "corpus_first"
    assert result["source_decision"].resolved_mode == "hybrid"


@pytest.mark.parametrize(
    ("live_sql_enabled", "live_sql_planned"),
    [(False, True), (True, False)],
    ids=["disabled", "not-planned"],
)
def test_corpus_evidence_does_not_expand_without_permitted_live_sql(
    live_sql_enabled: bool,
    live_sql_planned: bool,
) -> None:
    nodes, _ = _nodes(
        RuntimeError("judge unavailable"),
        live_sql_enabled=live_sql_enabled,
    )
    ctx = _corpus_first_context(live_sql_planned=live_sql_planned)
    original_hits = list(ctx["retrieved_hits"])

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "degrade"
    assert result["retrieved_hits"] == original_hits
    assert result["retry_count"] == 0
    assert result["degraded_reason"] == "evidence_sufficiency_unavailable"
    assert result["source_decision"].resolved_mode == "corpus_first"
    assert "source_expansion_from" not in result


def test_irrelevant_insufficient_evidence_abstains_and_clears_hits() -> None:
    nodes, _ = _nodes(
        _result(
            relevance="irrelevant",
            sufficiency="insufficient",
            supported=[],
            missing=["offer letter reference number"],
            action="abstain",
        )
    )

    result = nodes.evidence_gate(_context())

    assert result["verifier_decision"] == "degrade"
    assert result["retrieved_hits"] == []
    assert result["degraded"] is True
    assert result["degraded_reason"] == "insufficient_semantic_evidence"


def test_corrective_rewrite_is_bounded_to_one_retry() -> None:
    nodes, inference = _nodes(
        _result(
            relevance="mixed",
            sufficiency="insufficient",
            supported=["person name"],
            missing=["offer letter reference number"],
            action="rewrite",
        )
    )
    ctx = _context()

    first = nodes.evidence_gate(ctx)

    assert first["verifier_decision"] == "retry"
    assert first["retry_count"] == 1
    assert first["retrieved_hits"] == []
    assert len(first["query_rewritten"]) == 1

    first["retrieved_hits"] = [
        _hit("Touqeer is the recipient; no reference number is shown.")
    ]
    second = nodes.evidence_gate(first)

    assert second["verifier_decision"] == "degrade"
    assert second["retry_count"] == 1
    assert second["retrieved_hits"] == []
    assert len(second["query_rewritten"]) == 1
    assert len(inference.calls) == 2


def test_partial_evidence_retains_supported_hits_and_degrades() -> None:
    nodes, _ = _nodes(
        _result(
            relevance="relevant",
            sufficiency="partial",
            supported=["Touqeer is the recipient"],
            missing=["offer letter reference number"],
            action="partial",
        )
    )
    ctx = _context()
    original_hits = list(ctx["retrieved_hits"])

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "degrade"
    assert result["retrieved_hits"] == original_hits
    assert result["degraded"] is True
    assert result["degraded_reason"] == "partial_evidence"


def test_unavailable_evaluator_never_marks_evidence_verified() -> None:
    nodes, _ = _nodes(RuntimeError("judge unavailable"))
    ctx = _context()
    original_hits = list(ctx["retrieved_hits"])

    result = nodes.evidence_gate(ctx)

    assert result["verifier_decision"] == "degrade"
    assert result["retrieved_hits"] == original_hits
    assert result["degraded"] is True
    assert result["degraded_reason"] == "evidence_sufficiency_unavailable"
    assert result["evidence_sufficiency"].evaluator_status == "unavailable"
    assert result["execution_modes"]["evidence_gate"] == "fallback"
