import json

import pytest

from rag.query.answering.evidence_sufficiency import (
    evaluate_evidence_sufficiency,
    parse_evidence_sufficiency_result,
)
from rag.query.cancellation import QueryCancellationToken, QueryCancelled
from rag.query.qdrant import SearchHit


class FakeInference:
    def __init__(self, result: str | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def generate_json(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _hit(text: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id="internal-point-id",
        score=0.9,
        payload={"text": text, "doc_title": "Record.pdf", "page": 2, **payload},
    )


def _result(
    *,
    relevance: str = "relevant",
    sufficiency: str = "sufficient",
    supported: list[str] | None = None,
    missing: list[str] | None = None,
    action: str = "answer",
) -> str:
    return json.dumps(
        {
            "relevance": relevance,
            "sufficiency": sufficiency,
            "supported_aspects": supported
            if supported is not None
            else ["requested identifier"],
            "missing_aspects": missing if missing is not None else [],
            "action": action,
        }
    )


def test_relevant_evidence_can_still_be_insufficient() -> None:
    inference = FakeInference(
        _result(
            sufficiency="insufficient",
            supported=["requested person"],
            missing=["reference number"],
            action="general_search",
        )
    )

    result = evaluate_evidence_sufficiency(
        "What is the reference number for Touqeer?",
        [
            _hit(
                "Touqeer received an offer letter, but this excerpt omits its reference number."
            )
        ],
        inference=inference,  # type: ignore[arg-type]
        model="judge-model",
    )

    assert result.relevance == "relevant"
    assert result.sufficiency == "insufficient"
    assert result.supported_aspects == ("requested person",)
    assert result.missing_aspects == ("reference number",)
    assert result.action == "general_search"
    assert result.evaluator_status == "checked"
    assert inference.calls[0]["model"] == "judge-model"
    schema = inference.calls[0]["json_schema"]
    assert isinstance(schema, dict)
    assert set(schema["required"]) == {
        "relevance",
        "sufficiency",
        "supported_aspects",
        "missing_aspects",
        "action",
    }
    assert schema["additionalProperties"] is False


def test_prompt_is_bounded_and_whitelists_payload_fields() -> None:
    inference = FakeInference(_result())
    hits = [
        _hit(
            "x" * 10_000,
            section_title="Terms",
            connector_password="do-not-leak",
            database_dsn="postgres://secret",
        )
        for _ in range(20)
    ]

    evaluate_evidence_sufficiency(
        "Find the requested value",
        hits,
        inference=inference,  # type: ignore[arg-type]
        model=None,
    )

    prompt = str(inference.calls[0]["prompt"])
    assert "do-not-leak" not in prompt
    assert "postgres://secret" not in prompt
    assert "internal-point-id" not in prompt
    assert (
        prompt.count('"evidence_id"') == 8
    )  # total evidence budget is reached before the hit limit
    assert len(prompt) < 16_000


def test_incomplete_structural_coverage_vetoes_but_complete_coverage_does_not_prove_sufficiency() -> (
    None
):
    sufficient = evaluate_evidence_sufficiency(
        "List every obligation",
        [_hit("Obligation A and obligation B")],
        inference=FakeInference(_result(supported=["listed obligations"])),  # type: ignore[arg-type]
        model=None,
        structural_coverage="partial",
    )
    insufficient = evaluate_evidence_sufficiency(
        "List every obligation",
        [_hit("The document discusses obligations without listing them.")],
        inference=FakeInference(
            _result(
                sufficiency="insufficient",
                supported=["document subject"],
                missing=["obligation list"],
                action="rewrite",
            )
        ),  # type: ignore[arg-type]
        model=None,
        structural_coverage="complete",
    )

    assert sufficient.sufficiency == "partial"
    assert sufficient.action == "partial"
    assert "structural coverage" in sufficient.missing_aspects[-1].lower()
    assert insufficient.sufficiency == "insufficient"
    assert insufficient.action == "rewrite"


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n{}\n```",
        _result(relevance="unsupported"),
        _result(
            sufficiency="partial",
            supported=[],
            missing=["identifier"],
            action="partial",
        ),
        json.dumps(
            {
                "relevance": "relevant",
                "sufficiency": "sufficient",
                "supported_aspects": ["identifier"],
                "missing_aspects": [],
                "action": "answer",
                "extra": "not allowed",
            }
        ),
    ],
)
def test_parser_rejects_malformed_or_inconsistent_results(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_evidence_sufficiency_result(raw)


def test_evaluator_failure_is_explicit_and_cancellation_propagates() -> None:
    unavailable = evaluate_evidence_sufficiency(
        "Find the requested value",
        [_hit("Potential evidence")],
        inference=FakeInference(RuntimeError("provider unavailable")),  # type: ignore[arg-type]
        model=None,
    )

    assert unavailable.evaluator_status == "unavailable"
    assert unavailable.evaluator_error == "RuntimeError"
    assert unavailable.sufficiency == "unknown"
    assert unavailable.action == "partial"

    token = QueryCancellationToken()
    token.cancel()
    cancelled_inference = FakeInference(_result())
    with pytest.raises(QueryCancelled):
        evaluate_evidence_sufficiency(
            "Find the requested value",
            [_hit("Potential evidence")],
            inference=cancelled_inference,  # type: ignore[arg-type]
            model=None,
            cancellation_token=token,
        )
    assert cancelled_inference.calls == []


def test_no_usable_evidence_abstains_without_calling_the_evaluator() -> None:
    inference = FakeInference(_result())

    result = evaluate_evidence_sufficiency(
        "Find the requested value",
        [SearchHit(point_id="empty", score=0.8, payload={"database_dsn": "secret"})],
        inference=inference,  # type: ignore[arg-type]
        model=None,
    )

    assert result.relevance == "irrelevant"
    assert result.sufficiency == "insufficient"
    assert result.action == "abstain"
    assert result.evaluator_status == "not_needed"
    assert inference.calls == []
