"""Strict JSON generation helpers with one repair attempt."""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..query.cancellation import QueryCancellationToken, call_with_optional_cancellation


ModelT = TypeVar("ModelT", bound=BaseModel)


class LlmContractError(RuntimeError):
    pass


def generate_contract(
    *,
    inference: object,
    model: str | None,
    system: str,
    prompt: str,
    contract: type[ModelT],
    cancellation_token: QueryCancellationToken | None = None,
) -> ModelT:
    raw = _generate(
        inference=inference,
        model=model,
        system=system,
        prompt=prompt,
        cancellation_token=cancellation_token,
    )
    try:
        return contract.model_validate(_json_object(raw))
    except (ValueError, ValidationError) as first_error:
        repaired = _generate(
            inference=inference,
            model=model,
            system=system,
            prompt=_repair_prompt(raw=raw, error=first_error, contract=contract),
            cancellation_token=cancellation_token,
        )
        try:
            return contract.model_validate(_json_object(repaired))
        except (ValueError, ValidationError) as second_error:
            raise LlmContractError(f"{contract.__name__} validation failed after repair: {second_error}") from second_error


def _generate(
    *,
    inference: object,
    model: str | None,
    system: str,
    prompt: str,
    cancellation_token: QueryCancellationToken | None,
) -> str:
    generator = getattr(inference, "generate_json", None)
    if generator is not None:
        return str(
            call_with_optional_cancellation(
                generator,
                cancellation_token,
                prompt=prompt,
                model=model,
                system=system,
            )
        )
    answer = getattr(inference, "answer", None)
    if answer is None:
        raise LlmContractError("inference client does not support JSON generation")
    return str(
        call_with_optional_cancellation(
            answer,
            cancellation_token,
            question=f"{system}\n\n{prompt}",
            contexts=[],
        )
    )


def _json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model response did not contain a JSON object") from None
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return value


def _repair_prompt(*, raw: str, error: Exception, contract: type[BaseModel]) -> str:
    return (
        "Repair the invalid JSON so it exactly matches the supplied JSON Schema. "
        "Return only the corrected JSON object. Do not add commentary.\n\n"
        f"Validation error:\n{str(error)[:1800]}\n\n"
        f"JSON Schema:\n{json.dumps(contract.model_json_schema(), separators=(',', ':'))}\n\n"
        f"Invalid JSON:\n{raw[:12000]}"
    )

