from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.evaluations.answer_verifier import ANSWER_VERIFIER_VERSION, verify_answer_content_with_llm
from rag.evaluations.schemas import EvaluationCase
from rag.query.schemas import RAGResponse
from rag.shared.evaluation.answer_checks import evaluate_literal_checks


class FakeJsonLlm:
    def __init__(self, raw: str | list[str]) -> None:
        self.raw = [raw] if isinstance(raw, str) else list(raw)
        self.calls: list[dict[str, object]] = []

    def generate_json(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.raw.pop(0) if len(self.raw) > 1 else self.raw[0]


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
        '{"expected_answer_outcome": "not_applicable", '
        '"expected_answer_violations": [], "missing_must_include": [], '
        '"present_must_not_include": [], "confidence": 0.9}'
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
    assert result["version"] == "v8" == ANSWER_VERIFIER_VERSION
    assert result["confidence"] == 0.9
    assert llm.calls[0]["model"] == "judge-model"
    schema = llm.calls[0]["json_schema"]
    assert isinstance(schema, dict)
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["expected_answer_outcome"]["enum"] == ["not_applicable"]
    assert properties["missing_must_include"]["items"]["enum"] == [
        "chief financial officer"
    ]
    assert len(llm.calls) == 1


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
        '{"expected_answer_outcome": "not_satisfied", '
        '"expected_answer_violations": [{"kind": "contradiction", '
        '"detail": "The answer names the wrong officer."}], '
        '"missing_must_include": [], '
        '"present_must_not_include": ["chief operating officer"], '
        '"confidence": 0.99}'
    )

    verify_answer_content_with_llm(llm, case=case, response=rag_response, literal=literal, model=None)

    prompt = str(llm.calls[0]["prompt"])
    assert "materially equivalent" in prompt
    assert "any N of several alternatives" in prompt
    assert "Also enforce every must_include and must_not_include constraint" in prompt
    assert '"expected_answer": "The chief financial officer owns finance."' in prompt


def test_answer_verifier_bad_json_fails_closed() -> None:
    case = EvaluationCase(id="case", question="Q?", must_include=["alpha"])
    rag_response = response("beta")
    literal = evaluate_literal_checks(rag_response.answer, case.must_include, case.must_not_include)

    result = verify_answer_content_with_llm(
        FakeJsonLlm(["not json", "still not json"]),
        case=case,
        response=rag_response,
        literal=literal,
        model=None,
    )

    assert result["passed"] is False
    assert result["status"] == "error"


def test_answer_verifier_repairs_invalid_json_once() -> None:
    case = EvaluationCase(id="case", question="Q?", expected_answer="alpha")
    rag_response = response("alpha")
    literal = evaluate_literal_checks(
        rag_response.answer,
        case.must_include,
        case.must_not_include,
    )
    llm = FakeJsonLlm(
        [
            "The answer is correct.",
            '{"expected_answer_outcome": "satisfied", '
            '"expected_answer_violations": [], "missing_must_include": [], '
            '"present_must_not_include": [], "confidence": 0.95}',
        ]
    )

    result = verify_answer_content_with_llm(
        llm,
        case=case,
        response=rag_response,
        literal=literal,
        model=None,
    )

    assert result["passed"] is True
    assert result["status"] == "checked"
    assert len(llm.calls) == 2
    assert llm.calls[1]["json_schema"] == llm.calls[0]["json_schema"]
    assert "previous response was not a valid, complete, internally consistent" in str(
        llm.calls[1]["prompt"]
    )


def test_answer_verifier_does_not_rejudge_valid_negative_verdict() -> None:
    case = EvaluationCase(id="case", question="Q?", expected_answer="alpha")
    rag_response = response("beta")
    literal = evaluate_literal_checks(
        rag_response.answer,
        case.must_include,
        case.must_not_include,
    )
    llm = FakeJsonLlm(
        '{"expected_answer_outcome": "not_satisfied", '
        '"expected_answer_violations": [{"kind": "missing_fact", '
        '"detail": "The answer omits alpha."}], "missing_must_include": [], '
        '"present_must_not_include": [], "confidence": 0.99}'
    )

    result = verify_answer_content_with_llm(
        llm,
        case=case,
        response=rag_response,
        literal=literal,
        model=None,
    )

    assert result["passed"] is False
    assert result["missing_expected_facts"] == ["The answer omits alpha."]
    assert result["reason"] == "The answer omits alpha."
    assert len(llm.calls) == 1


def test_answer_verifier_repairs_json_with_missing_required_keys() -> None:
    case = EvaluationCase(id="case", question="Q?", expected_answer="alpha")
    rag_response = response("alpha")
    literal = evaluate_literal_checks(
        rag_response.answer,
        case.must_include,
        case.must_not_include,
    )
    llm = FakeJsonLlm(
        [
            '{"passed": true}',
            '{"expected_answer_outcome": "satisfied", '
            '"expected_answer_violations": [], "missing_must_include": [], '
            '"present_must_not_include": [], "confidence": 0.95}',
        ]
    )

    result = verify_answer_content_with_llm(
        llm,
        case=case,
        response=rag_response,
        literal=literal,
        model=None,
    )

    assert result["passed"] is True
    assert len(llm.calls) == 2


def test_answer_verifier_derives_pass_from_empty_issue_lists() -> None:
    case = EvaluationCase(
        id="case",
        question="Name any two options.",
        expected_answer="Any two of alpha, beta, or gamma.",
    )
    rag_response = response("Alpha and beta.")
    literal = evaluate_literal_checks(
        rag_response.answer,
        case.must_include,
        case.must_not_include,
    )
    llm = FakeJsonLlm(
        '{"expected_answer_outcome": "satisfied", '
        '"expected_answer_violations": [], "missing_must_include": [], '
        '"present_must_not_include": [], "confidence": 0.95}'
    )

    result = verify_answer_content_with_llm(
        llm,
        case=case,
        response=rag_response,
        literal=literal,
        model=None,
    )

    assert result["passed"] is True
    assert result["expected_answer_outcome"] == "satisfied"
    assert result["expected_answer_satisfied"] is True
    assert result["missing_expected_facts"] == []
    assert len(llm.calls) == 1


def test_answer_verifier_rejects_unknown_constraint_labels() -> None:
    case = EvaluationCase(
        id="case",
        question="Q?",
        must_include=["alpha"],
    )
    rag_response = response("beta")
    literal = evaluate_literal_checks(
        rag_response.answer,
        case.must_include,
        case.must_not_include,
    )
    llm = FakeJsonLlm(
        '{"expected_answer_outcome": "not_applicable", '
        '"expected_answer_violations": [], '
        '"missing_must_include": ["a different requirement"], '
        '"present_must_not_include": [], "confidence": 0.9}'
    )

    result = verify_answer_content_with_llm(
        llm,
        case=case,
        response=rag_response,
        literal=literal,
        model=None,
    )

    assert result["passed"] is False
    assert result["status"] == "error"
    assert len(llm.calls) == 2


@pytest.mark.parametrize(
    "outcome,violations",
    [
        ("not_satisfied", "[]"),
        (
            "satisfied",
            '[{"kind": "missing_fact", "detail": "A required fact is absent."}]',
        ),
    ],
)
def test_answer_verifier_rejects_inconsistent_expected_answer_outcome(
    outcome: str,
    violations: str,
) -> None:
    case = EvaluationCase(id="case", question="Q?", expected_answer="alpha")
    rag_response = response("beta")
    literal = evaluate_literal_checks(
        rag_response.answer,
        case.must_include,
        case.must_not_include,
    )
    llm = FakeJsonLlm(
        f'{{"expected_answer_outcome": "{outcome}", '
        f'"expected_answer_violations": {violations}, '
        '"missing_must_include": [], "present_must_not_include": [], '
        '"confidence": 0.9}'
    )

    result = verify_answer_content_with_llm(
        llm,
        case=case,
        response=rag_response,
        literal=literal,
        model=None,
    )

    assert result["passed"] is False
    assert result["status"] == "error"
    assert len(llm.calls) == 2


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
