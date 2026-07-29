"""LLM judge for semantic evaluation answer-content checks."""

from __future__ import annotations

import json

from rag.evaluations.schemas import EvaluationCase
from ..query.schemas import RAGResponse
from ..shared.evaluation.answer_checks import LiteralCheckResult


ANSWER_VERIFIER_VERSION = "v8"
_REQUIRED_VERDICT_KEYS = frozenset(
    {
        "expected_answer_outcome",
        "expected_answer_violations",
        "missing_must_include",
        "present_must_not_include",
        "confidence",
    }
)
_EXPECTED_ANSWER_OUTCOMES = frozenset(
    {"satisfied", "not_satisfied", "uncertain", "not_applicable"}
)
_EXPECTED_VIOLATION_KINDS = frozenset(
    {"contradiction", "missing_fact", "uncertainty"}
)


def verify_answer_content_with_llm(
    llm: object,
    *,
    case: EvaluationCase,
    response: RAGResponse,
    literal: LiteralCheckResult,
    model: str | None,
    interrupt_error_types: tuple[type[Exception], ...] = (),
) -> dict[str, object]:
    generator = getattr(llm, "generate_json", None)
    if generator is None:
        return _unavailable("generate_json_unavailable")
    prompt = _answer_verifier_prompt(case=case, response=response, literal=literal)
    json_schema = _answer_verifier_json_schema(case)
    try:
        raw = generator(
            prompt=prompt,
            model=model,
            system="You are a strict RAG evaluation answer-content judge.",
            max_tokens=512,
            json_schema=json_schema,
        )
        try:
            payload = _load_verdict(
                str(raw),
                expected_answer_supplied=case.expected_answer is not None,
                must_include=case.must_include,
                must_not_include=case.must_not_include,
            )
        except (json.JSONDecodeError, ValueError):
            raw = generator(
                prompt=_answer_verifier_repair_prompt(
                    original_prompt=prompt,
                ),
                model=model,
                system="You repair a RAG evaluation verdict into one valid JSON object.",
                max_tokens=512,
                json_schema=json_schema,
            )
            payload = _load_verdict(
                str(raw),
                expected_answer_supplied=case.expected_answer is not None,
                must_include=case.must_include,
                must_not_include=case.must_not_include,
            )
    except Exception as exc:  # noqa: BLE001 - eval judge must fail closed per case
        if isinstance(exc, interrupt_error_types):
            raise
        return {
            "used": True,
            "version": ANSWER_VERIFIER_VERSION,
            "status": "error",
            "passed": False,
            "error_type": type(exc).__name__,
        }
    return {
        "used": True,
        "version": ANSWER_VERIFIER_VERSION,
        "status": "checked",
        "passed": payload["passed"],
        "expected_answer_outcome": payload["expected_answer_outcome"],
        "expected_answer_satisfied": payload["expected_answer_outcome"]
        in {"satisfied", "not_applicable"},
        "missing_expected_facts": _violation_details(
            payload.get("expected_answer_violations")
        ),
        "missing_must_include": _string_list(payload.get("missing_must_include")),
        "present_must_not_include": _string_list(payload.get("present_must_not_include")),
        "reason": _verdict_reason(payload),
        "confidence": _confidence(payload.get("confidence")),
    }


def _answer_verifier_json_schema(case: EvaluationCase) -> dict[str, object]:
    outcome_values = (
        ["satisfied", "not_satisfied", "uncertain"]
        if case.expected_answer is not None
        else ["not_applicable"]
    )
    violation_schema: dict[str, object] = {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": sorted(_EXPECTED_VIOLATION_KINDS),
                },
                "detail": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
            },
            "required": ["kind", "detail"],
        },
    }
    if case.expected_answer is None:
        violation_schema["maxItems"] = 0
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "expected_answer_outcome": {
                "type": "string",
                "enum": outcome_values,
            },
            "expected_answer_violations": violation_schema,
            "missing_must_include": _constraint_array_schema(case.must_include),
            "present_must_not_include": _constraint_array_schema(
                case.must_not_include
            ),
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
        },
        "required": sorted(_REQUIRED_VERDICT_KEYS),
    }


def _constraint_array_schema(allowed: list[str]) -> dict[str, object]:
    allowed_values = list(dict.fromkeys(allowed))
    item_schema: dict[str, object] = {"type": "string"}
    if allowed_values:
        item_schema["enum"] = allowed_values
    return {
        "type": "array",
        "items": item_schema,
        "maxItems": len(allowed_values),
    }


def _answer_verifier_prompt(
    *,
    case: EvaluationCase,
    response: RAGResponse,
    literal: LiteralCheckResult,
) -> str:
    payload = {
        "question": case.question,
        "expected_answer": case.expected_answer,
        "answer": response.answer,
        "must_include": case.must_include,
        "must_not_include": case.must_not_include,
        "deterministic_missing_must_include": list(literal.missing_must_include),
        "deterministic_present_must_not_include": list(literal.present_must_not_include),
    }
    return (
        "Judge only whether the answer content satisfies the evaluation expectations. "
        "Do not judge retrieval, source selection, citations, or faithfulness. "
        "When expected_answer is supplied, require the answer to be materially equivalent: "
        "it must preserve every material fact and must not contradict the expected answer. "
        "Honor cardinality and choice language exactly: when an expectation says any N "
        "of several alternatives, N valid alternatives are enough; do not require all of them. "
        "Also enforce every must_include and must_not_include constraint. "
        "Treat paraphrases, abbreviations, formatting differences, reasonable rounding, "
        "and unit conversions as satisfying the same content. "
        "Be strict with different numeric values, decimal shifts, dates, years, names, and negation. "
        "A forbidden must_not_include item fails if the answer asserts that forbidden content. "
        "Return only JSON with keys expected_answer_outcome, "
        "expected_answer_violations, missing_must_include, "
        "present_must_not_include, and confidence. expected_answer_outcome must be "
        "satisfied, not_satisfied, uncertain, or not_applicable. If no "
        "expected_answer is supplied, use not_applicable and no violations. If one "
        "is supplied, use satisfied with no violations only when it is materially "
        "satisfied. For not_satisfied or uncertain, include at least one violation "
        "object with kind (missing_fact, contradiction, or uncertainty) and a "
        "concrete detail. The application derives the final result from these fields. "
        "In missing_must_include and present_must_not_include, copy only exact strings "
        "from the corresponding supplied constraint arrays.\n\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)}"
    )


def _answer_verifier_repair_prompt(
    *,
    original_prompt: str,
) -> str:
    return (
        f"{original_prompt}\n\n"
        "Your previous response was not a valid, complete, internally consistent "
        "verdict. Re-evaluate independently and return a fresh JSON object only, "
        "without markdown, commentary, or code fences. Do not rely on the previous "
        "verdict."
    )


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "used": False,
        "version": ANSWER_VERIFIER_VERSION,
        "status": reason,
        "passed": False,
    }


def _load_json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("answer verifier did not return JSON") from None
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("answer verifier returned non-object JSON")
    return value


def _load_verdict(
    raw: str,
    *,
    expected_answer_supplied: bool,
    must_include: list[str],
    must_not_include: list[str],
) -> dict[str, object]:
    payload = _load_json_object(raw)
    missing_keys = sorted(_REQUIRED_VERDICT_KEYS.difference(payload))
    if missing_keys:
        raise ValueError(
            "answer verifier verdict is missing required keys: "
            + ", ".join(missing_keys)
        )
    for key in ("missing_must_include", "present_must_not_include"):
        value = payload[key]
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ValueError(f"answer verifier {key} must be a list of strings")
    outcome = payload["expected_answer_outcome"]
    if outcome not in _EXPECTED_ANSWER_OUTCOMES:
        raise ValueError("answer verifier expected-answer outcome is invalid")
    violations = payload["expected_answer_violations"]
    if not isinstance(violations, list) or any(
        not _valid_expected_violation(item) for item in violations
    ):
        raise ValueError(
            "answer verifier expected-answer violations are invalid"
        )
    confidence = payload["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        raise ValueError("answer verifier confidence must be a number from 0 to 1")
    if not expected_answer_supplied and (
        outcome != "not_applicable" or violations
    ):
        raise ValueError(
            "answer verifier cannot report expected-answer issues when none was supplied"
        )
    if expected_answer_supplied and outcome == "not_applicable":
        raise ValueError(
            "answer verifier cannot skip a supplied expected answer"
        )
    if (
        outcome in {"satisfied", "not_applicable"}
        and violations
    ) or (
        outcome in {"not_satisfied", "uncertain"}
        and not violations
    ):
        raise ValueError(
            "answer verifier expected-answer verdict is internally inconsistent"
        )
    if not _reported_constraints_are_known(
        payload["missing_must_include"],
        allowed=must_include,
    ):
        raise ValueError(
            "answer verifier reported an unknown must-include constraint"
        )
    if not _reported_constraints_are_known(
        payload["present_must_not_include"],
        allowed=must_not_include,
    ):
        raise ValueError(
            "answer verifier reported an unknown must-not-include constraint"
        )
    payload["passed"] = (
        outcome in {"satisfied", "not_applicable"}
        and not violations
        and not payload["missing_must_include"]
        and not payload["present_must_not_include"]
    )
    return payload


def _valid_expected_violation(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    kind = value.get("kind")
    detail = value.get("detail")
    return (
        kind in _EXPECTED_VIOLATION_KINDS
        and isinstance(detail, str)
        and bool(detail.strip())
        and len(detail) <= 500
    )


def _violation_details(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        detail.strip()
        for item in value
        if isinstance(item, dict)
        and isinstance((detail := item.get("detail")), str)
        and detail.strip()
    ]


def _verdict_reason(payload: dict[str, object]) -> str:
    if payload["passed"] is True:
        return "All answer-content criteria were satisfied."
    issues = _violation_details(payload.get("expected_answer_violations"))
    issues.extend(
        f"Missing required content: {item}"
        for item in _string_list(payload.get("missing_must_include"))
    )
    issues.extend(
        f"Forbidden content present: {item}"
        for item in _string_list(payload.get("present_must_not_include"))
    )
    return _compact_text("; ".join(issues), max_chars=500)


def _reported_constraints_are_known(
    reported: object,
    *,
    allowed: list[str],
) -> bool:
    if not isinstance(reported, list):
        return False
    normalized_allowed = {_normalized_constraint(item) for item in allowed}
    return all(
        _normalized_constraint(item) in normalized_allowed
        for item in reported
        if isinstance(item, str)
    )


def _normalized_constraint(value: str) -> str:
    return " ".join(value.casefold().split())


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item).strip())]


def _compact_text(value: object, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars]


def _confidence(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))
