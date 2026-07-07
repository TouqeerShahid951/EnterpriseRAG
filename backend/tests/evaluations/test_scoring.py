from rag.evaluations.scoring import score_case_result
from rag.schemas.evaluations import EvaluationCase
from rag.schemas.query import RAGResponse


def response(answer: str) -> RAGResponse:
    return RAGResponse(
        trace_id="trace",
        answer=answer,
        sources=[],
        artifacts=[],
        artifact_job=None,
        conflict_flag=False,
        conflict_detail=None,
        faithfulness_score=1.0,
        faithfulness_status="checked",
        unfounded_claims=[],
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
