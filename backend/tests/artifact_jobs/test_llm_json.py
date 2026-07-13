from __future__ import annotations

from pydantic import BaseModel
import pytest

from rag.artifact_jobs.llm_json import LlmContractError, generate_contract


class _ExampleContract(BaseModel):
    title: str


def test_generate_contract_extracts_json_object_from_prose() -> None:
    generator = _SequenceGenerator(
        ['Model output follows:\n```json\n{"title":"Quarterly review"}\n```']
    )

    result = generate_contract(
        inference=generator,  # type: ignore[arg-type]
        model="reasoning-model",
        system="Return JSON",
        prompt="Build a title",
        contract=_ExampleContract,
    )

    assert result.title == "Quarterly review"
    assert len(generator.calls) == 1


def test_generate_contract_repairs_invalid_response_once() -> None:
    generator = _SequenceGenerator(
        ["{}", '{"title":"Repaired quarterly review"}']
    )

    result = generate_contract(
        inference=generator,  # type: ignore[arg-type]
        model="reasoning-model",
        system="Return JSON",
        prompt="Build a title",
        contract=_ExampleContract,
    )

    assert result.title == "Repaired quarterly review"
    assert len(generator.calls) == 2
    assert generator.calls[0] == {
        "prompt": "Build a title",
        "model": "reasoning-model",
        "system": "Return JSON",
    }
    assert generator.calls[1]["model"] == "reasoning-model"
    assert generator.calls[1]["system"] == "Return JSON"
    assert "Repair the invalid JSON" in generator.calls[1]["prompt"]
    assert "Invalid JSON:\n{}" in generator.calls[1]["prompt"]


def test_generate_contract_raises_after_one_failed_repair() -> None:
    generator = _SequenceGenerator(["{}", "still invalid"])

    with pytest.raises(LlmContractError, match="validation failed after repair"):
        generate_contract(
            inference=generator,  # type: ignore[arg-type]
            model=None,
            system="Return JSON",
            prompt="Build a title",
            contract=_ExampleContract,
        )

    assert len(generator.calls) == 2


def test_generate_contract_rejects_non_string_provider_output() -> None:
    generator = _SequenceGenerator([{"title": "not a string"}])

    with pytest.raises(LlmContractError, match="non-string response"):
        generate_contract(
            inference=generator,  # type: ignore[arg-type]
            model=None,
            system="Return JSON",
            prompt="Build a title",
            contract=_ExampleContract,
        )

    assert len(generator.calls) == 1


class _SequenceGenerator:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, str | None]] = []

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
    ) -> object:
        self.calls.append({"prompt": prompt, "model": model, "system": system})
        return self.responses.pop(0)
