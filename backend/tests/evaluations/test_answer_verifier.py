from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.evaluations.answer_verifier import ANSWER_VERIFIER_VERSION, verify_answer_content_with_llm
from rag.evaluations.schemas import EvaluationCase
from rag.query.schemas import RAGResponse
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
    assert result["version"] == "v2" == ANSWER_VERIFIER_VERSION
    assert result["confidence"] == 0.9
    assert llm.calls[0]["model"] == "judge-model"


def test_answer_verifier_prompt_requires_expected_answer_equivalence_and_literal_constraints() -> None:
    case = EvaluationCase(
        id="case",
        question="Who owns finance?",
        expected_answer="The chief financial officer owns finance.",
        must_include=["finance"],
        must_not_include=["chief operating officer"],
    )
    rag_response = response("The chief operating officer owns finance.")
    literal = evaluate_literal_checks(rag_response.answer, case.must_include, case.must_not_include)
    llm = FakeJsonLlm(
        '{"passed": false, "missing_must_include": [], '
        '"present_must_not_include": ["chief operating officer"]}'
    )

    verify_answer_content_with_llm(llm, case=case, response=rag_response, literal=literal, model=None)

    prompt = str(llm.calls[0]["prompt"])
    assert "materially equivalent" in prompt
    assert "Also enforce every must_include and must_not_include constraint" in prompt
    assert '"expected_answer": "The chief financial officer owns finance."' in prompt


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


def test_answer_verifier_propagates_worker_interrupts() -> None:
    case = EvaluationCase(id="case", question="Q?", must_include=["alpha"])
    rag_response = response("beta")
    literal = evaluate_literal_checks(
        rag_response.answer,
        case.must_include,
        case.must_not_include,
    )

    class InterruptedLlm:
        def generate_json(self, **_kwargs: object) -> str:
            raise SoftTimeLimitExceeded()

    with pytest.raises(SoftTimeLimitExceeded):
        verify_answer_content_with_llm(
            InterruptedLlm(),
            case=case,
            response=rag_response,
            literal=literal,
            model=None,
            interrupt_error_types=(SoftTimeLimitExceeded,),
        )
