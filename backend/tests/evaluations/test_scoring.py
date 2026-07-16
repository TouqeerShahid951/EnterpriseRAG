from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.evaluations.scoring import score_case_result, summarize_results
from rag.evaluations.schemas import EvaluationCase
from rag.query.schemas import RAGResponse, SourceAnchor


def response(
    answer: str,
    *,
    faithfulness_score: float = 1.0,
    faithfulness_status: str = "checked",
    sources: list[SourceAnchor] | None = None,
    unfounded_claims: list[str] | None = None,
) -> RAGResponse:
    return RAGResponse(
        trace_id="trace",
        answer=answer,
        sources=sources or [],
        artifacts=[],
        artifact_job=None,
        conflict_flag=False,
        conflict_detail=None,
        faithfulness_score=faithfulness_score,
        faithfulness_status=faithfulness_status,
        unfounded_claims=unfounded_claims or [],
        intent="factual_simple",
        session_id="session",
        latency_ms=0,
        node_timings=[],
        degraded=False,
        degraded_reason=None,
    )


def test_score_case_result_uses_llm_answer_content_fallback() -> None:
    case = EvaluationCase(
        id="case",
        question="Who owns finance?",
        must_include=["chief financial officer"],
    )

    scored = score_case_result(
        case,
        response=response("The CFO owns finance."),
        diagnostic={},
        answer_content_judge=lambda *_args: {
            "used": True,
            "status": "checked",
            "passed": True,
            "reason": "CFO means chief financial officer.",
        },
    )

    assert scored["passed"] is True
    assert scored["checks"]["answer_content"]["passed"] is True
    assert scored["checks"]["answer_content"]["literal_passed"] is False
    assert scored["checks"]["answer_content"]["missing_must_include"] == []
    assert scored["checks"]["answer_content"]["llm_verifier"]["passed"] is True


def test_score_case_result_does_not_let_llm_override_forbidden_content() -> None:
    def fail_if_called(*_args):
        raise AssertionError("LLM judge should not run for must_not_include failures")

    scored = score_case_result(
        EvaluationCase(
            id="case",
            question="What is supported?",
            must_not_include=["unsupported claim"],
        ),
        response=response("This includes an unsupported claim."),
        diagnostic={},
        answer_content_judge=fail_if_called,
    )

    assert scored["passed"] is False
    assert scored["primary_failure_stage"] == "answer_content"
    assert scored["checks"]["answer_content"]["llm_verifier"] is None


def test_score_case_result_rejects_contradictory_llm_pass() -> None:
    scored = score_case_result(
        EvaluationCase(
            id="case",
            question="Who owns finance?",
            must_include=["chief financial officer"],
        ),
        response=response("The CFO owns finance."),
        diagnostic={},
        answer_content_judge=lambda *_args: {
            "used": True,
            "status": "checked",
            "passed": True,
            "missing_must_include": ["chief financial officer"],
        },
    )

    assert scored["passed"] is False
    assert scored["checks"]["answer_content"]["passed"] is False


def test_score_case_result_propagates_worker_interrupts_from_the_judge() -> None:
    def interrupt(*_args: object) -> dict[str, object]:
        raise SoftTimeLimitExceeded()

    with pytest.raises(SoftTimeLimitExceeded):
        score_case_result(
            EvaluationCase(
                id="case",
                question="Who owns finance?",
                must_include=["chief financial officer"],
            ),
            response=response("The CFO owns finance."),
            diagnostic={},
            answer_content_judge=interrupt,
            interrupt_error_types=(SoftTimeLimitExceeded,),
        )


def test_expected_answer_always_uses_semantic_judge_despite_literal_pass() -> None:
    calls = 0

    def judge(*_args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"used": True, "version": "v2", "status": "checked", "passed": False}

    scored = score_case_result(
        EvaluationCase(
            id="case",
            question="Who owns finance?",
            expected_answer="The chief operating officer owns finance.",
            must_include=["chief financial officer"],
        ),
        response=response("The chief financial officer owns finance."),
        diagnostic={},
        answer_content_judge=judge,
    )

    assert calls == 1
    assert scored["passed"] is False
    assert scored["primary_failure_stage"] == "answer_content"
    assert scored["checks"]["answer_content"]["literal_passed"] is True
    assert scored["checks"]["answer_content"]["required"] is True


def test_expected_answer_only_is_an_expectation_and_requires_semantic_pass() -> None:
    calls = 0

    def judge(*_args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"used": True, "version": "v2", "status": "checked", "passed": True}

    scored = score_case_result(
        EvaluationCase(
            id="case",
            question="Who owns finance?",
            expected_answer="The CFO owns finance.",
        ),
        response=response("The chief financial officer owns finance."),
        diagnostic={},
        answer_content_judge=judge,
    )

    assert calls == 1
    assert scored["passed"] is True
    assert scored["checks"]["dataset"]["passed"] is True
    assert scored["checks"]["answer_content"]["passed"] is True


def test_expected_answer_judge_cannot_override_forbidden_content() -> None:
    calls = 0

    def judge(*_args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"used": True, "version": "v2", "status": "checked", "passed": True}

    scored = score_case_result(
        EvaluationCase(
            id="case",
            question="Who owns finance?",
            expected_answer="The CFO owns finance.",
            must_not_include=["unsupported claim"],
        ),
        response=response("The CFO owns finance; this is an unsupported claim."),
        diagnostic={},
        answer_content_judge=judge,
    )

    assert calls == 1
    assert scored["passed"] is False
    assert scored["checks"]["answer_content"]["present_must_not_include"] == ["unsupported claim"]


@pytest.mark.parametrize(
    ("judge", "expected_status"),
    [
        (None, "unavailable"),
        (
            lambda *_args: {
                "used": False,
                "version": "v2",
                "status": "generate_json_unavailable",
                "passed": False,
            },
            "generate_json_unavailable",
        ),
    ],
)
def test_expected_answer_fails_closed_without_checked_judge(judge, expected_status: str) -> None:
    scored = score_case_result(
        EvaluationCase(id="case", question="Who owns finance?", expected_answer="The CFO owns finance."),
        response=response("The CFO owns finance."),
        diagnostic={},
        answer_content_judge=judge,
    )

    assert scored["passed"] is False
    assert scored["checks"]["answer_content"]["llm_verifier"]["status"] == expected_status


def test_expected_answer_fails_closed_when_judge_errors() -> None:
    def error(*_args: object) -> dict[str, object]:
        raise RuntimeError("judge unavailable")

    scored = score_case_result(
        EvaluationCase(id="case", question="Who owns finance?", expected_answer="The CFO owns finance."),
        response=response("The CFO owns finance."),
        diagnostic={},
        answer_content_judge=error,
    )

    assert scored["passed"] is False
    assert scored["checks"]["answer_content"]["llm_verifier"]["status"] == "error"


def test_literal_pass_without_expected_answer_keeps_judge_optional() -> None:
    def fail_if_called(*_args: object) -> dict[str, object]:
        raise AssertionError("optional judge should not run after a literal pass")

    scored = score_case_result(
        EvaluationCase(id="case", question="Who owns finance?", must_include=["CFO"]),
        response=response("The CFO owns finance."),
        diagnostic={},
        answer_content_judge=fail_if_called,
    )

    assert scored["passed"] is True
    assert scored["checks"]["answer_content"]["required"] is False
    assert scored["checks"]["answer_content"]["llm_verifier"] is None


def test_citations_resolve_exactly_to_returned_sources_per_occurrence() -> None:
    source = _source()
    scored = score_case_result(
        EvaluationCase(
            id="case",
            question="What is supported?",
            must_cite_source=True,
            min_faithfulness_score=0.8,
        ),
        response=response(
            "Supported [live:row-alpha]. Repeated [live:row-alpha].",
            sources=[source],
        ),
        diagnostic={},
    )

    assert scored["passed"] is True
    assert scored["checks"]["citation"] == {
        "passed": True,
        "required": True,
        "citations": ["[live:row-alpha]", "[live:row-alpha]"],
        "resolved_citations": ["[live:row-alpha]", "[live:row-alpha]"],
        "unresolved_citations": [],
    }


def test_one_unresolved_citation_fails_the_whole_citation_check() -> None:
    scored = score_case_result(
        EvaluationCase(id="case", question="What is supported?", must_cite_source=True),
        response=response(
            "Supported [live:row-alpha]. Fabricated [fake:123].",
            sources=[_source()],
        ),
        diagnostic={},
    )

    assert scored["passed"] is False
    assert scored["primary_failure_stage"] == "citation"
    assert scored["checks"]["citation"] == {
        "passed": False,
        "required": True,
        "citations": ["[live:row-alpha]", "[fake:123]"],
        "resolved_citations": ["[live:row-alpha]"],
        "unresolved_citations": ["[fake:123]"],
    }


def test_required_citation_fails_when_answer_has_no_citation_token() -> None:
    scored = score_case_result(
        EvaluationCase(id="case", question="What is supported?", must_cite_source=True),
        response=response("Supported.", sources=[_source()]),
        diagnostic={},
    )

    assert scored["passed"] is False
    assert scored["checks"]["citation"] == {
        "passed": False,
        "required": True,
        "citations": [],
        "resolved_citations": [],
        "unresolved_citations": [],
    }


def test_optional_unresolved_citation_still_fails() -> None:
    scored = score_case_result(
        EvaluationCase(id="case", question="What is supported?", must_include=["Supported"]),
        response=response("Supported [fake:123]."),
        diagnostic={},
    )

    assert scored["passed"] is False
    assert scored["primary_failure_stage"] == "citation"
    assert scored["checks"]["citation"]["required"] is False
    assert scored["checks"]["citation"]["unresolved_citations"] == ["[fake:123]"]


def test_optional_answer_without_citations_keeps_citation_check_passed() -> None:
    scored = score_case_result(
        EvaluationCase(id="case", question="What is supported?", must_include=["Supported"]),
        response=response("Supported."),
        diagnostic={},
    )

    assert scored["passed"] is True
    assert scored["checks"]["citation"] == {
        "passed": True,
        "required": False,
        "citations": [],
        "resolved_citations": [],
        "unresolved_citations": [],
    }


def test_must_cite_requires_checked_faithfulness_even_at_zero_threshold() -> None:
    scored = score_case_result(
        EvaluationCase(id="case", question="What is supported?", must_cite_source=True),
        response=response(
            "Supported [live:row-alpha].",
            sources=[_source()],
            faithfulness_status="skipped",
        ),
        diagnostic={},
    )

    assert scored["passed"] is False
    assert scored["primary_failure_stage"] == "faithfulness"
    assert scored["checks"]["citation"]["passed"] is True
    assert scored["checks"]["faithfulness"]["required"] is True
    assert scored["checks"]["faithfulness"]["status"] == "not_evaluated"


@pytest.mark.parametrize(
    ("score", "unfounded_claims"),
    [(0.79, []), (0.9, ["Unsupported detail."])],
)
def test_required_faithfulness_rejects_low_score_or_unfounded_claims(
    score: float, unfounded_claims: list[str]
) -> None:
    scored = score_case_result(
        EvaluationCase(
            id="case",
            question="What is supported?",
            must_cite_source=True,
            min_faithfulness_score=0.8,
        ),
        response=response(
            "Supported [live:row-alpha].",
            sources=[_source()],
            faithfulness_score=score,
            unfounded_claims=unfounded_claims,
        ),
        diagnostic={},
    )

    assert scored["passed"] is False
    assert scored["primary_failure_stage"] == "faithfulness"
    assert scored["checks"]["faithfulness"]["status"] == "failed"


def test_skipped_faithfulness_is_not_counted_as_a_pass() -> None:
    scored = score_case_result(
        EvaluationCase(id="case", question="Who owns finance?", must_include=["CFO"]),
        response=response("The CFO owns finance.", faithfulness_status="skipped"),
        diagnostic={},
    )

    assert scored["passed"] is True
    assert scored["checks"]["faithfulness"] == {
        "passed": None,
        "status": "not_evaluated",
        "source_status": "skipped",
        "score": None,
        "min_score": 0.0,
        "required": False,
        "unfounded_claims": [],
    }


def test_required_skipped_faithfulness_fails_the_case() -> None:
    scored = score_case_result(
        EvaluationCase(id="case", question="Who owns finance?", min_faithfulness_score=0.8),
        response=response("The CFO owns finance.", faithfulness_status="skipped"),
        diagnostic={},
    )

    assert scored["passed"] is False
    assert scored["primary_failure_stage"] == "faithfulness"


def test_faithfulness_summary_excludes_unmeasured_checks() -> None:
    summary = summarize_results(
        [
            _summary_row("passed", True),
            _summary_row("failed", False),
            _summary_row("not_evaluated", None),
            _summary_row("error", None),
        ]
    )

    assert summary["faithfulness_pass_rate"] == 0.5
    assert summary["faithfulness_coverage_rate"] == 0.5
    assert summary["faithfulness_evaluated_count"] == 2
    assert summary["faithfulness_not_evaluated_count"] == 1
    assert summary["faithfulness_error_count"] == 1


def test_all_skipped_faithfulness_has_no_pass_rate() -> None:
    summary = summarize_results([_summary_row("not_evaluated", None)])

    assert summary["faithfulness_pass_rate"] is None
    assert summary["faithfulness_coverage_rate"] == 0.0


def test_semantic_judge_summary_reports_required_coverage() -> None:
    summary = summarize_results(
        [
            _semantic_summary_row("checked", True),
            _semantic_summary_row("checked", False),
            _semantic_summary_row("unavailable", False),
            _semantic_summary_row("error", False),
            {"passed": True, "checks": {"answer_content": {"required": False}}, "latency_ms": 0},
        ]
    )

    assert summary["semantic_judge_pass_rate"] == 0.5
    assert summary["semantic_judge_coverage_rate"] == 0.5
    assert summary["semantic_judge_required_count"] == 4
    assert summary["semantic_judge_evaluated_count"] == 2
    assert summary["semantic_judge_not_evaluated_count"] == 1
    assert summary["semantic_judge_error_count"] == 1


def _summary_row(status: str, passed: bool | None) -> dict[str, object]:
    return {
        "passed": True,
        "checks": {"faithfulness": {"status": status, "passed": passed}},
        "latency_ms": 0,
    }


def _semantic_summary_row(status: str, passed: bool) -> dict[str, object]:
    return {
        "passed": passed,
        "checks": {
            "answer_content": {
                "required": True,
                "passed": passed,
                "llm_verifier": {"status": status, "passed": passed, "version": "v2"},
            }
        },
        "latency_ms": 0,
    }


def _source() -> SourceAnchor:
    return SourceAnchor(
        doc_id="live",
        doc_title="Live DB",
        chunk_id="live:row-alpha",
        excerpt="Supported.",
        group_path="/quality",
    )
