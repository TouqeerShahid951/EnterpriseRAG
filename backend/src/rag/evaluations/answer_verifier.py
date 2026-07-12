"""LLM fallback judge for semantic evaluation answer-content checks."""

from __future__ import annotations

import json

from ..schemas.evaluations import EvaluationCase
from ..schemas.query import RAGResponse
from ..shared.evaluation.answer_checks import LiteralCheckResult


ANSWER_VERIFIER_VERSION = "v1"


def verify_answer_content_with_llm(
    llm: object,
    *,
    case: EvaluationCase,
    response: RAGResponse,
    literal: LiteralCheckResult,
    model: str | None,
) -> dict[str, object]:
    generator = getattr(llm, "generate_json", None)
    if generator is None:
        return _unavailable("generate_json_unavailable")
    try:
        raw = generator(
            prompt=_answer_verifier_prompt(case=case, response=response, literal=literal),
            model=model,
            system="You are a strict RAG evaluation answer-content judge.",
            max_tokens=512,
        )
        payload = _load_json_object(str(raw))
    except Exception as exc:  # noqa: BLE001 - eval judge must fail closed per case
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
        "passed": bool(payload.get("passed") is True),
        "missing_must_include": _string_list(payload.get("missing_must_include")),
        "present_must_not_include": _string_list(payload.get("present_must_not_include")),
        "reason": _compact_text(payload.get("reason"), max_chars=500),
        "confidence": _confidence(payload.get("confidence")),
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
        "Treat paraphrases, abbreviations, formatting differences, reasonable rounding, "
        "and unit conversions as satisfying the same content. "
        "Be strict with different numeric values, decimal shifts, dates, years, names, and negation. "
        "A forbidden must_not_include item fails if the answer asserts that forbidden content. "
        "Return only JSON with keys passed, missing_must_include, present_must_not_include, reason, and confidence. "
        "Use passed=true only when every must_include is semantically present and no must_not_include is asserted.\n\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)}"
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
