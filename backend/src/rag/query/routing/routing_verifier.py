"""LLM verifier for ambiguous or risky route decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass

from rag.query.cancellation import QueryCancellationToken, call_with_optional_cancellation
from rag.query.routing.routing_models import QuerySignals, RouteIntent

_VALID_INTENTS: set[RouteIntent] = {
    "factual_simple",
    "procedural",
    "summarization",
    "comparison",
    "temporal",
    "temporal_comparison",
    "multi_hop",
    "aggregation",
    "graphrag_global",
    "conflict_check",
    "troubleshooting",
    "document_navigation",
    "conversational_followup",
    "out_of_scope",
    "general_rag",
    "troubleshooting_procedure",
    "comparative_summary",
    "temporal_factual",
}
_ROUTE_VERIFIER_QUERY_CHARS = 2500
_ROUTE_VERIFIER_SIGNAL_TOKENS = 40


@dataclass(frozen=True)
class RouteVerifierDecision:
    intent: RouteIntent
    secondary_intents: tuple[RouteIntent, ...]
    confidence: float
    debug_reason: str


def verify_route_with_llm(
    ollama: object,
    *,
    model: str | None,
    signals: QuerySignals,
    candidate_scores: dict[RouteIntent, float],
    cancellation_token: QueryCancellationToken | None = None,
) -> RouteVerifierDecision | None:
    verifier = getattr(ollama, "verify_route", None)
    if verifier is None:
        return None
    raw = call_with_optional_cancellation(
        verifier,
        cancellation_token,
        prompt=build_route_verifier_prompt(signals, candidate_scores),
        model=model,
    )
    return parse_route_verifier_result(raw)


def build_route_verifier_prompt(signals: QuerySignals, candidate_scores: dict[RouteIntent, float]) -> str:
    candidates = [
        {"intent": intent, "score": round(score, 3)}
        for intent, score in sorted(candidate_scores.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    original_query = _query_excerpt(signals.original_query)
    resolved_query = (
        "<same as original query>"
        if signals.resolved_query.strip() == signals.original_query.strip()
        else _query_excerpt(signals.resolved_query)
    )
    return (
        "Choose the best RAG route for the user query. "
        "Use only the query and routing signals. Do not answer the query. "
        "Return only valid JSON with keys: intent, secondary_intents, confidence, debug_reason. "
        "intent must be one of: "
        + ", ".join(sorted(_VALID_INTENTS))
        + ". secondary_intents must be a list. confidence must be 0 to 1. "
        "Prefer general_rag when no specialized route is clearly justified.\n\n"
        f"Original query:\n{original_query}\n\n"
        f"Resolved query:\n{resolved_query}\n\n"
        f"Signals:\n{json.dumps(_signal_summary(signals), sort_keys=True)}\n\n"
        f"Rule candidates:\n{json.dumps(candidates, sort_keys=True)}"
    )


def parse_route_verifier_result(raw: str) -> RouteVerifierDecision:
    payload = _load_json_object(raw)
    intent = _parse_intent(payload.get("intent"))
    secondaries = tuple(_parse_secondary_intents(payload.get("secondary_intents")))
    confidence = _clamp_score(payload.get("confidence"))
    debug_reason = payload.get("debug_reason")
    return RouteVerifierDecision(
        intent=intent,
        secondary_intents=secondaries,
        confidence=confidence,
        debug_reason=debug_reason.strip() if isinstance(debug_reason, str) and debug_reason.strip() else "llm verifier",
    )


def _signal_summary(signals: QuerySignals) -> dict[str, object]:
    return {
        "token_count": len(signals.tokens),
        "tokens": signals.tokens[:_ROUTE_VERIFIER_SIGNAL_TOKENS],
        "domain_entity_clues": signals.domain_entity_clues,
        "temporal_clues": signals.temporal_clues,
        "followup_clues": signals.followup_clues,
        "has_session_context": signals.has_session_context,
        "is_short_query": signals.is_short_query,
        "is_vague_followup": signals.is_vague_followup,
        "clarity_bonus": signals.clarity_bonus,
    }


def _query_excerpt(text: str, max_chars: int = _ROUTE_VERIFIER_QUERY_CHARS) -> str:
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    head_chars = max_chars * 3 // 4
    tail_chars = max_chars - head_chars
    omitted = len(clean) - max_chars
    return f"{clean[:head_chars]}\n...[{omitted} chars omitted]...\n{clean[-tail_chars:]}"


def _load_json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("route verifier did not return JSON") from None
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("route verifier returned non-object JSON")
    return value


def _parse_intent(value: object) -> RouteIntent:
    if not isinstance(value, str) or value not in _VALID_INTENTS:
        raise ValueError("route verifier returned an invalid intent")
    return value  # type: ignore[return-value]


def _parse_secondary_intents(value: object) -> list[RouteIntent]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("secondary_intents must be a list")
    intents: list[RouteIntent] = []
    for item in value[:4]:
        if isinstance(item, str) and item in _VALID_INTENTS and item not in intents:
            intents.append(item)  # type: ignore[arg-type]
    return intents


def _clamp_score(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("confidence must be numeric")
    if isinstance(value, str):
        value = float(value)
    if not isinstance(value, int | float):
        raise ValueError("confidence must be numeric")
    return max(0.0, min(1.0, float(value)))
