"""Compatibility facade for the production intent router."""

from __future__ import annotations

from dataclasses import dataclass

from .routing_models import QuerySignals
from .routing_rules import score_route_rules, should_call_llm_verifier
from .routing_signals import extract_query_signals

LLM_VERIFIER_FALLBACK_THRESHOLD = 0.85


@dataclass(frozen=True)
class IntentSignalScores:
    factual: float = 0.0
    procedural: float = 0.0
    summarization: float = 0.0
    comparison: float = 0.0
    temporal: float = 0.0
    aggregation: float = 0.0
    conflict: float = 0.0
    document_navigation: float = 0.0
    follow_up: float = 0.0


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    confidence: float
    signals: IntentSignalScores
    verified_by_llm: bool = False
    rationale: str = ""


class ProductionIntentRouter:
    def __init__(self, verifier: object | None = None) -> None:
        self.verifier = verifier

    def route(self, query: str, *, session_turns: list[dict[str, object]] | None = None) -> IntentDecision:
        signals = extract_query_signals(query, session_turns or [])
        result = score_route_rules(signals)
        signal_scores = _signal_scores(signals, result.raw_scores)
        if self.verifier is not None and should_call_llm_verifier(result):
            verified = _call_test_verifier(
                self.verifier,
                query=query,
                candidate_intent=result.intent,
                confidence=result.confidence,
                signals=signal_scores,
            )
            if verified is not None:
                return IntentDecision(
                    intent=str(verified.get("intent", result.intent)),
                    confidence=float(verified.get("confidence", result.confidence)),
                    signals=signal_scores,
                    verified_by_llm=True,
                    rationale=str(verified.get("rationale", "llm verifier")),
                )
        return IntentDecision(
            intent=_compat_intent_name(result.intent),
            confidence=result.confidence,
            signals=signal_scores,
            verified_by_llm=False,
            rationale=result.debug_reason,
        )


def extract_intent_signals(query: str, session_turns: list[dict[str, object]] | None = None) -> IntentSignalScores:
    signals = extract_query_signals(query, session_turns or [])
    result = score_route_rules(signals)
    return _signal_scores(signals, result.raw_scores)


def _signal_scores(signals: QuerySignals, raw_scores: dict[str, float]) -> IntentSignalScores:
    return IntentSignalScores(
        factual=_confidence(raw_scores.get("factual_simple", 0.0)),
        procedural=_confidence(raw_scores.get("procedural", 0.0)),
        summarization=_confidence(raw_scores.get("summarization", 0.0)),
        comparison=_confidence(raw_scores.get("comparison", 0.0)),
        temporal=max(_confidence(raw_scores.get("temporal", 0.0)), 1.0 if signals.temporal_clues else 0.0),
        aggregation=_confidence(raw_scores.get("aggregation", 0.0)),
        conflict=_confidence(raw_scores.get("conflict_check", 0.0)),
        document_navigation=_confidence(raw_scores.get("document_navigation", 0.0)),
        follow_up=1.0 if signals.is_vague_followup else _confidence(raw_scores.get("conversational_followup", 0.0)),
    )


def _confidence(score: float) -> float:
    return max(0.0, min(1.0, score / 0.70))


def _compat_intent_name(intent: str) -> str:
    return {
        "factual_simple": "factual",
        "conflict_check": "conflict",
        "conversational_followup": "follow_up",
    }.get(intent, intent)


def _call_test_verifier(
    verifier: object,
    *,
    query: str,
    candidate_intent: str,
    confidence: float,
    signals: IntentSignalScores,
) -> dict[str, object] | None:
    verify_intent = getattr(verifier, "verify_intent", None)
    if verify_intent is None:
        return None
    result = verify_intent(
        query=query,
        candidate_intent=candidate_intent,
        confidence=confidence,
        signals=signals,
    )
    return result if isinstance(result, dict) else None
