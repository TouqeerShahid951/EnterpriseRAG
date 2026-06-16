"""Optional LLM-assisted reasoning helpers for query graph stages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .cancellation import QueryCancellationToken, QueryCancelled, call_with_optional_cancellation
from .routing_models import RouteIntent


ExecutionMode = str
_DETERMINISTIC_SPLIT_INTENTS = {
    "comparison",
    "temporal_comparison",
    "comparative_summary",
}


@dataclass(frozen=True)
class ReasoningResult:
    values: list[str]
    mode: ExecutionMode
    detail: str | None = None


@dataclass(frozen=True)
class TemporalScopeResult:
    target_date: str | None
    is_historical: bool | None
    mode: ExecutionMode
    detail: str | None = None


def plan_sub_queries_with_reasoning(
    *,
    ollama: object,
    model: str | None,
    query: str,
    intent: RouteIntent | str,
    fallback: list[str],
    cancellation_token: QueryCancellationToken | None = None,
) -> ReasoningResult:
    fallback_values = _dedupe_non_empty(fallback) or [query]
    planner = getattr(ollama, "plan_query", None)
    if planner is None or not _eligible_query(query):
        return ReasoningResult(fallback_values, "deterministic")
    if str(intent) in _DETERMINISTIC_SPLIT_INTENTS and len(fallback_values) > 1:
        return ReasoningResult(fallback_values, "deterministic")
    try:
        raw = call_with_optional_cancellation(
            planner,
            cancellation_token,
            prompt=_planner_prompt(query=query, intent=str(intent)),
            model=model,
        )
        planned = _parse_string_list(raw, "sub_queries", limit=4)
        if planned:
            return ReasoningResult(planned, "ai_assisted")
    except QueryCancelled:
        raise
    except (TypeError, ValueError, RuntimeError):
        pass
    return ReasoningResult(fallback_values, "fallback", "planner_fallback")


def rewrite_query_with_reasoning(
    *,
    ollama: object,
    model: str | None,
    query: str,
    retry_count: int,
    fallback: str,
    cancellation_token: QueryCancellationToken | None = None,
) -> ReasoningResult:
    rewriter = getattr(ollama, "rewrite_query", None)
    if rewriter is None:
        return ReasoningResult([fallback], "deterministic")
    try:
        raw = call_with_optional_cancellation(
            rewriter,
            cancellation_token,
            prompt=_rewrite_prompt(query=query, retry_count=retry_count),
            model=model,
        )
        rewritten = _parse_single_string(raw, "query")
        if rewritten:
            return ReasoningResult([rewritten], "ai_assisted")
    except QueryCancelled:
        raise
    except (TypeError, ValueError, RuntimeError):
        pass
    return ReasoningResult([fallback], "fallback", "rewrite_fallback")


def extract_temporal_scope_with_reasoning(
    *,
    ollama: object,
    model: str | None,
    query: str,
    cancellation_token: QueryCancellationToken | None = None,
) -> TemporalScopeResult:
    extractor = getattr(ollama, "extract_temporal_scope", None)
    if extractor is None:
        return TemporalScopeResult(None, None, "deterministic")
    try:
        raw = call_with_optional_cancellation(
            extractor,
            cancellation_token,
            prompt=_temporal_prompt(query),
            model=model,
        )
        payload = _load_json_object(raw)
        target_date = payload.get("target_date")
        is_historical = payload.get("is_historical")
        if target_date is not None and not _valid_iso_date(str(target_date)):
            target_date = None
        if is_historical is not None and not isinstance(is_historical, bool):
            is_historical = None
        if target_date is not None or is_historical is not None:
            return TemporalScopeResult(
                str(target_date) if target_date else None,
                is_historical,
                "ai_assisted",
            )
    except QueryCancelled:
        raise
    except (TypeError, ValueError, RuntimeError):
        pass
    return TemporalScopeResult(None, None, "fallback", "temporal_fallback")


def _planner_prompt(*, query: str, intent: str) -> str:
    return (
        "Decompose this enterprise RAG query into at most four focused retrieval sub-queries. "
        "Return only JSON with keys sub_queries and reasoning. Do not answer the query. "
        "Each sub-query must preserve the user's meaning and be useful for document retrieval.\n\n"
        f"Intent: {intent}\nQuery: {query}"
    )


def _rewrite_prompt(*, query: str, retry_count: int) -> str:
    strategy = ("expand acronyms", "broaden topic", "remove narrow constraints")[min(retry_count, 2)]
    return (
        "Rewrite this failed retrieval query for another search attempt. "
        "Return only JSON with key query. Preserve the user's meaning. "
        f"Strategy: {strategy}\nQuery: {query}"
    )


def _temporal_prompt(query: str) -> str:
    return (
        "Extract temporal retrieval scope from this query. Return only JSON with keys "
        "is_historical and target_date. target_date must be YYYY-MM-DD or null. "
        "Use null when no precise date can be inferred.\n\n"
        f"Query: {query}"
    )


def _parse_string_list(raw: str, key: str, *, limit: int) -> list[str]:
    value = _load_json_object(raw).get(key)
    if not isinstance(value, list):
        return []
    return _dedupe_non_empty(str(item).strip() for item in value)[:limit]


def _parse_single_string(raw: str, key: str) -> str | None:
    value = _load_json_object(raw).get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _load_json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("reasoning response did not contain JSON") from None
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("reasoning response was not a JSON object")
    return value


def _dedupe_non_empty(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _eligible_query(query: str) -> bool:
    return len(query.split()) >= 3


def _valid_iso_date(value: str) -> bool:
    return re.fullmatch(r"(19|20)\d{2}-\d{2}-\d{2}", value) is not None
