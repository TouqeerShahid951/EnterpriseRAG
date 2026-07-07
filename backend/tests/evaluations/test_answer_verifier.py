from rag.evaluations.answer_verifier import verify_answer_content_with_llm
from rag.schemas.evaluations import EvaluationCase
from rag.schemas.query import RAGResponse
from rag.shared.evaluation.answer_checks import evaluate_literal_checks


class FakeJsonLlm:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.calls: list[dict[str, object]] = []

    def generate_json(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.raw


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


def test_answer_verifier_accepts_semantic_match_json() -> None:
    case = EvaluationCase(
        id="case",
        question="Who owns finance?",
        must_include=["chief financial officer"],
    )
    rag_response = response("The CFO owns finance.")
    literal = evaluate_literal_checks(rag_response.answer, case.must_include, case.must_not_include)
    llm = FakeJsonLlm(
        '{"passed": true, "missing_must_include": [], "present_must_not_include": [], '
        '"reason": "CFO means chief financial officer.", "confidence": 0.9}'
    )

    result = verify_answer_content_with_llm(
        llm,
        case=case,
        response=rag_response,
        literal=literal,
        model="judge-model",
    )

    assert result["passed"] is True
    assert result["status"] == "checked"
    assert result["confidence"] == 0.9
    assert llm.calls[0]["model"] == "judge-model"


def test_answer_verifier_bad_json_fails_closed() -> None:
    case = EvaluationCase(id="case", question="Q?", must_include=["alpha"])
    rag_response = response("beta")
    literal = evaluate_literal_checks(rag_response.answer, case.must_include, case.must_not_include)

    result = verify_answer_content_with_llm(
        FakeJsonLlm("not json"),
        case=case,
        response=rag_response,
        literal=literal,
        model=None,
    )

    assert result["passed"] is False
    assert result["status"] == "error"
