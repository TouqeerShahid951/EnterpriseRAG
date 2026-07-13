"""Compatibility helpers for query intent and simple sub-query planning."""

from __future__ import annotations

import re

from .schemas import QueryIntent
from .routing_models import RouteIntent, public_intent_for
from .routing_rules import score_route_rules
from .routing_signals import extract_query_signals

_DATE_RE = re.compile(r"\b(19|20)\d{2}(-\d{2}){0,2}\b")


def classify_intent(query: str) -> QueryIntent:
    route = score_route_rules(extract_query_signals(query, [])).intent
    return public_intent_for(route)


def should_include_superseded(query: str) -> bool:
    text = query.lower()
    historical_terms = ("as of", "historical", "previous", "old", "superseded", "before")
    return _DATE_RE.search(query) is not None or any(term in text for term in historical_terms)


def plan_sub_queries(query: str, intent: QueryIntent | RouteIntent | str) -> list[str]:
    if intent in {"factual_simple", "conversational", "conversational_followup", "general_rag", "out_of_scope"}:
        return [query]
    if intent in {"multi_hop", "comparison", "temporal_comparison", "comparative_summary", "troubleshooting"}:
        parts = [
            _clean_sub_query_part(part)
            for part in re.split(r"\b(?:and|versus|vs\.?|compared with|compared to)\b", query, flags=re.IGNORECASE)
        ]
        planned = [part for part in parts if part]
        return planned[:4] or [query]
    return [query]


def resolve_conversational_query(query: str, turns: list[dict[str, object]]) -> str:
    if not turns:
        return query
    previous = turns[-1].get("query")
    if not isinstance(previous, str) or not previous:
        return query
    return f"{query}\nPrevious user question: {previous}"


def rewrite_for_retry(query: str, retry_count: int) -> str:
    strategies = (
        "Expand acronyms and retrieve broadly",
        "Broaden to the closest document topic",
        "Remove narrow constraints but keep the original meaning",
    )
    strategy = strategies[min(retry_count, len(strategies) - 1)]
    return f"{strategy}: {query}"


def _clean_sub_query_part(part: str) -> str:
    return part.strip(" ?.")
