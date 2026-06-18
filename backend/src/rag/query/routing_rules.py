"""Weighted deterministic rules for query intent routing."""

from __future__ import annotations

import re

from .routing_models import QuerySignals, RouteIntent, RoutePenalty, RuleHit, RuleRouteResult

STRONG_WEIGHT = 0.40
MEDIUM_WEIGHT = 0.25
WEAK_WEIGHT = 0.10
TEMPORAL_CLUE_WEIGHT = WEAK_WEIGHT
DOMAIN_ENTITY_BONUS = 0.10
CLARITY_BONUS = 0.10
VAGUE_FOLLOWUP_PENALTY = -0.25
SHORT_QUERY_PENALTY = -0.20
COMPETING_INTENT_PENALTY = -0.15
CONFLICTING_SIGNAL_PENALTY = -0.20
RULE_ACCEPT_CONFIDENCE = 0.85
LLM_VERIFIER_FLOOR = 0.55
INTENT_MARGIN_THRESHOLD = 0.20

_SIGNALS: dict[RouteIntent, dict[str, tuple[str, ...]]] = {
    "factual_simple": {
        "strong": ("what is", "who is", "where is", "when is", "which", "define", "tell me"),
        "medium": ("does", "is there", "what does", "who does", "where can"),
        "weak": ("explain", "identify", "find"),
    },
    "general_rag": {
        "strong": ("tell me everything", "everything about", "all about"),
        "medium": ("broad overview", "full overview"),
        "weak": ("tell me about",),
    },
    "procedural": {
        "strong": ("how do i", "how to", "steps", "steps to", "give me the steps", "procedure", "process"),
        "medium": ("workflow", "instructions", "guide", "required steps", "walk me through"),
        "weak": ("do this", "complete", "apply"),
    },
    "summarization": {
        "strong": ("summarize", "summary", "short summary", "brief overview", "tl;dr"),
        "medium": ("overview", "recap", "key points", "main points"),
        "weak": ("brief", "digest"),
    },
    "comparison": {
        "strong": ("compare", "difference between", "what changed", "changed from", "compared to", "versus", " vs ", "better than"),
        "medium": ("differences", "similarities", "contrast", "which is better", "added after", "changed in", "changes in"),
        "weak": ("against", "between"),
    },
    "temporal": {
        "strong": ("as of", "latest", "current", "currently", "historical", "still valid"),
        "medium": ("previous", "old", "before", "after", "changed"),
        "weak": ("date", "version", "timeline", "valid", "updated", "update"),
    },
    "multi_hop": {
        "strong": ("based on", "depends on", "relationship between", "support both", "both"),
        "medium": ("and also", "also require", "then", "using both", "across"),
        "weak": ("also", "combine"),
    },
    "aggregation": {
        "strong": (
            "how many",
            "count",
            "total",
            "number of",
            "list all",
            "list of all",
            "list the",
            "give me the list",
            "show all",
        ),
        "medium": ("all of the", "all the", "every", "sum", "updated in"),
        "weak": ("list", "enumerate"),
    },
    "conflict_check": {
        "strong": (
            "conflict",
            "contradict",
            "contradictory",
            "contradiction",
            "inconsistent",
            "one document says",
            "another says",
            "one says",
            "which one is correct",
        ),
        "medium": ("disagree", "mismatch", "competing claims"),
        "weak": ("different answers", "not aligned"),
    },
    "troubleshooting": {
        "strong": ("troubleshoot", "not working", "not booting", "memory error", "login issues", "error", "failed", "failure"),
        "medium": ("cause", "fix", "resolve", "diagnose", "symptom", "booting", "what should i check"),
        "weak": ("issue", "issues", "problem", "broken"),
    },
    "document_navigation": {
        "strong": (
            "which page",
            "what page",
            "where in the document",
            "where in the manual",
            "where in manual",
            "source section",
            "open section",
        ),
        "medium": ("section", "chapter", "page", "citation", "find the source", "talk about"),
        "weak": ("where is", "located"),
    },
    "out_of_scope": {
        "strong": ("weather", "stock price", "sports score", "news today", "next election", "write me a poem"),
        "medium": ("write code", "book a flight", "restaurant", "poem"),
        "weak": ("joke",),
    },
}
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}(?:-\d{2}){0,2}\b")
_SUPERLATIVE_RE = re.compile(r"\b(?:highest|lowest|maximum|minimum|max|min|largest|smallest|most|least)\b")
_EXHAUSTIVE_SUMMARY_RE = re.compile(r"\b(?:summari[sz]e|summary|overview|recap)\b")
_EXHAUSTIVE_SCOPE_RE = re.compile(r"\b(?:all|every)\b")
_DOCUMENT_CLASS_RE = re.compile(
    r"\b(?:firs?|documents?|docs?|files?|pdfs?|polic(?:y|ies)|contracts?|reports?|manuals?|forms?)\b"
)
_COMPATIBLE_COMBINATIONS: dict[frozenset[RouteIntent], RouteIntent] = {
    frozenset(("temporal", "comparison")): "temporal_comparison",
    frozenset(("procedural", "troubleshooting")): "troubleshooting_procedure",
    frozenset(("summarization", "comparison")): "comparative_summary",
    frozenset(("factual_simple", "temporal")): "temporal_factual",
}
_COMBINATION_PRIORITY: tuple[tuple[RouteIntent, RouteIntent], ...] = (
    ("procedural", "troubleshooting"),
    ("summarization", "comparison"),
    ("temporal", "comparison"),
    ("factual_simple", "temporal"),
)


def score_route_rules(signals: QuerySignals) -> RuleRouteResult:
    scores: dict[RouteIntent, float] = {}
    hits: list[RuleHit] = []
    penalties: list[RoutePenalty] = []
    for intent, groups in _SIGNALS.items():
        intent_hits = _hits_for_intent(intent, groups, signals.normalized_query)
        if not intent_hits:
            continue
        score = sum(hit.weight for hit in intent_hits)
        hits.extend(intent_hits)
        if signals.domain_entity_clues:
            score += DOMAIN_ENTITY_BONUS
            hits.append(RuleHit(intent, "domain_entity_clue", DOMAIN_ENTITY_BONUS, "bonus", signals.domain_entity_clues[0]))
        if signals.clarity_bonus:
            score += CLARITY_BONUS
            hits.append(RuleHit(intent, "query_clarity", CLARITY_BONUS, "bonus", "clear query"))
        scores[intent] = score

    if signals.temporal_clues:
        scores["temporal"] = scores.get("temporal", 0.0) + TEMPORAL_CLUE_WEIGHT
        hits.append(RuleHit("temporal", "temporal_clue", TEMPORAL_CLUE_WEIGHT, "weak", signals.temporal_clues[0]))
    if _DATE_RE.search(signals.normalized_query):
        scores["temporal"] = scores.get("temporal", 0.0) + STRONG_WEIGHT
        hits.append(RuleHit("temporal", "explicit_date", STRONG_WEIGHT, "strong", _DATE_RE.search(signals.normalized_query).group(0)))  # type: ignore[union-attr]
    superlative = _SUPERLATIVE_RE.search(signals.normalized_query)
    if superlative is not None:
        scores["aggregation"] = scores.get("aggregation", 0.0) + MEDIUM_WEIGHT
        hits.append(RuleHit("aggregation", "table_superlative", MEDIUM_WEIGHT, "medium", superlative.group(0)))
    if _has_exhaustive_document_summary_signal(signals.normalized_query):
        scores["aggregation"] = scores.get("aggregation", 0.0) + STRONG_WEIGHT
        hits.append(
            RuleHit(
                "aggregation",
                "exhaustive_summary_document_class",
                STRONG_WEIGHT,
                "strong",
                "summarize all document class",
            )
        )
    if signals.use_conversation_memory:
        scores["conversational_followup"] = scores.get("conversational_followup", 0.0) + STRONG_WEIGHT + CLARITY_BONUS
        hits.append(RuleHit("conversational_followup", "session_followup", STRONG_WEIGHT, "strong", signals.followup_clues[0]))
    elif signals.is_vague_followup:
        penalties.append(RoutePenalty(None, "vague_followup_without_session_context", VAGUE_FOLLOWUP_PENALTY))

    scores, penalties = _apply_penalties(scores, penalties, signals)
    if not scores:
        return _fallback_result(signals, tuple(penalties))

    intent, secondary, top_score, margin = _select_intent(scores)
    confidence = _confidence_from_score(top_score)
    debug_reason = f"top score {top_score:.2f}, margin {margin:.2f}"
    return RuleRouteResult(
        intent=intent,
        secondary_intents=secondary,
        confidence=confidence,
        margin=margin,
        raw_scores=scores,
        rule_hits=tuple(hits),
        penalties=tuple(penalties),
        debug_reason=debug_reason,
    )


def should_call_llm_verifier(result: RuleRouteResult) -> bool:
    if result.confidence < LLM_VERIFIER_FLOOR:
        return False
    if _has_unambiguous_explicit_date_route(result):
        return False
    return result.confidence < RULE_ACCEPT_CONFIDENCE or result.margin < INTENT_MARGIN_THRESHOLD


def is_rule_route_accepted(result: RuleRouteResult) -> bool:
    return result.confidence >= RULE_ACCEPT_CONFIDENCE and result.margin >= INTENT_MARGIN_THRESHOLD


def _has_unambiguous_explicit_date_route(result: RuleRouteResult) -> bool:
    return (
        result.intent in {"temporal", "temporal_factual"}
        and result.margin >= 0.4
        and any(hit.signal == "explicit_date" for hit in result.rule_hits)
    )


def _hits_for_intent(
    intent: RouteIntent,
    groups: dict[str, tuple[str, ...]],
    text: str,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for strength, weight in (("strong", STRONG_WEIGHT), ("medium", MEDIUM_WEIGHT), ("weak", WEAK_WEIGHT)):
        for phrase in groups.get(strength, ()):
            if _phrase_matches(phrase, text):
                hits.append(RuleHit(intent, phrase.strip(), weight, strength, phrase.strip()))
    return hits


def _apply_penalties(
    scores: dict[RouteIntent, float],
    penalties: list[RoutePenalty],
    signals: QuerySignals,
) -> tuple[dict[RouteIntent, float], list[RoutePenalty]]:
    adjusted = dict(scores)
    if signals.is_short_query:
        for intent in list(adjusted):
            if signals.use_conversation_memory and intent in {"conversational_followup", "temporal"}:
                continue
            adjusted[intent] += SHORT_QUERY_PENALTY
            penalties.append(RoutePenalty(intent, "short_query", SHORT_QUERY_PENALTY))
    if signals.is_vague_followup and not signals.use_conversation_memory:
        for intent in list(adjusted):
            adjusted[intent] += VAGUE_FOLLOWUP_PENALTY
    ordered = sorted(adjusted.items(), key=lambda item: item[1], reverse=True)
    if len(ordered) > 1 and ordered[1][1] >= 0.35 and _combined_intent(ordered[0], ordered[1]) is None:
        pair = {ordered[0][0], ordered[1][0]}
        if not (signals.use_conversation_memory and pair == {"temporal", "conversational_followup"}):
            for intent in (ordered[0][0], ordered[1][0]):
                adjusted[intent] += COMPETING_INTENT_PENALTY
                penalties.append(RoutePenalty(intent, "competing_intent", COMPETING_INTENT_PENALTY))
    if adjusted.get("out_of_scope", 0.0) >= 0.35 and len(adjusted) > 1:
        for intent in list(adjusted):
            if intent != "out_of_scope":
                adjusted[intent] += CONFLICTING_SIGNAL_PENALTY
                penalties.append(RoutePenalty(intent, "conflicting_out_of_scope_signal", CONFLICTING_SIGNAL_PENALTY))
    return {intent: max(0.0, score) for intent, score in adjusted.items() if score > 0.0}, penalties


def _phrase_matches(phrase: str, text: str) -> bool:
    if phrase.startswith(" ") or phrase.endswith(" "):
        return phrase in text
    return re.search(rf"\b{re.escape(phrase.strip())}\b", text) is not None


def _has_exhaustive_document_summary_signal(text: str) -> bool:
    return (
        _EXHAUSTIVE_SUMMARY_RE.search(text) is not None
        and _EXHAUSTIVE_SCOPE_RE.search(text) is not None
        and _DOCUMENT_CLASS_RE.search(text) is not None
    )


def _select_intent(scores: dict[RouteIntent, float]) -> tuple[RouteIntent, tuple[RouteIntent, ...], float, float]:
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if scores.get("temporal", 0.0) >= 0.35 and scores.get("conversational_followup", 0.0) >= 0.35:
        top_score = max(scores["temporal"], scores["conversational_followup"])
        margin = _margin_excluding(scores, top_score, {"temporal", "conversational_followup"})
        return "temporal", ("conversational_followup",), top_score, margin

    if (
        scores.get("aggregation", 0.0) >= 0.35
        and scores.get("temporal", 0.0) >= 0.35
        and scores.get("comparison", 0.0) < 0.35
    ):
        top_score = max(scores["aggregation"], scores["temporal"])
        margin = _margin_excluding(scores, top_score, {"aggregation", "temporal"})
        return "aggregation", ("temporal",), top_score, margin

    for first, second in _COMBINATION_PRIORITY:
        combined = _COMPATIBLE_COMBINATIONS[frozenset((first, second))]
        if scores.get(first, 0.0) >= 0.35 and scores.get(second, 0.0) >= 0.35:
            top_score = max(scores[first], scores[second])
            margin = _margin_excluding(scores, top_score, {first, second})
            return combined, (first, second), top_score, margin

    intent, top_score = ordered[0]
    secondary: tuple[RouteIntent, ...] = ()
    if len(ordered) > 1:
        combined = _combined_intent(ordered[0], ordered[1])
        if combined is not None:
            intent = combined
            secondary = (ordered[0][0], ordered[1][0])
            top_score = max(ordered[0][1], ordered[1][1])
            return intent, secondary, top_score, _margin_excluding(scores, top_score, set(secondary))
    margin = top_score - (ordered[1][1] if len(ordered) > 1 else 0.0)
    return intent, secondary, top_score, margin


def _margin_excluding(scores: dict[RouteIntent, float], top_score: float, excluded: set[RouteIntent]) -> float:
    competitors = [score for intent, score in scores.items() if intent not in excluded]
    return top_score - max(competitors, default=0.0)


def _combined_intent(
    first: tuple[RouteIntent, float],
    second: tuple[RouteIntent, float],
) -> RouteIntent | None:
    if first[1] < 0.35 or second[1] < 0.35:
        return None
    return _COMPATIBLE_COMBINATIONS.get(frozenset((first[0], second[0])))


def _confidence_from_score(score: float) -> float:
    return max(0.0, min(1.0, score / 0.70))


def _fallback_result(signals: QuerySignals, penalties: tuple[RoutePenalty, ...]) -> RuleRouteResult:
    intent: RouteIntent = "conversational_followup" if signals.use_conversation_memory else "general_rag"
    return RuleRouteResult(
        intent=intent,
        secondary_intents=(),
        confidence=0.50 if intent == "general_rag" else 0.70,
        margin=0.0,
        raw_scores={},
        rule_hits=(),
        penalties=penalties,
        debug_reason="no deterministic route signals",
    )
