"""Governed selection of one authorized database source."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Literal

from rag.query.cancellation import QueryCancelled
from rag.query.sources.source_catalog import VisibleQuerySource

DatabaseRouteOutcome = Literal["selected", "clarification", "no_match"]


@dataclass(frozen=True)
class DatabaseRouteCandidate:
    source_id: str
    catalog_id: str
    name: str
    description: str


@dataclass(frozen=True)
class DatabaseRouteDecision:
    outcome: DatabaseRouteOutcome
    selected_catalog_id: str | None
    candidates: tuple[DatabaseRouteCandidate, ...]
    reason: str
    clarification_question: str | None = None
    router_mode: str = "deterministic"


def route_database_source(
    question: str,
    sources: list[VisibleQuerySource],
    *,
    client: object | None,
    model: str | None,
    cancellation_token: object | None = None,
) -> DatabaseRouteDecision:
    """Choose one source from an already-authorized list or request clarification."""

    if not sources:
        return DatabaseRouteDecision(
            outcome="no_match",
            selected_catalog_id=None,
            candidates=(),
            reason="no_authorized_database_sources",
            clarification_question=None,
        )
    ranked = sorted(
        ((_routing_score(question, source), source) for source in sources),
        key=lambda item: (item[0], item[1].name.lower()),
        reverse=True,
    )
    if len(ranked) == 1:
        return _selected(ranked[0][1], reason="only_authorized_database_source")
    top_score, top_source = ranked[0]
    second_score = ranked[1][0]
    if top_score >= 2 and top_score - second_score >= 2:
        return _selected(top_source, reason=f"unique_metadata_match:{top_score}:{second_score}")

    shortlist = [source for _score, source in ranked[:5]]
    generator = getattr(client, "generate_json", None) if client is not None else None
    if generator is None or not model:
        return _clarification(shortlist, reason="database_router_unavailable")
    try:
        raw = generator(
            prompt=_routing_prompt(question, shortlist),
            model=model,
            system=(
                "Select one authorized enterprise database source using only the supplied routing metadata. "
                "Return strict JSON and request clarification when multiple sources remain plausible."
            ),
            cancellation_token=cancellation_token,
            max_tokens=700,
        )
        payload = _json_object(raw)
    except QueryCancelled:
        raise
    except Exception as exc:
        return _clarification(
            shortlist,
            reason=f"database_router_failed:{type(exc).__name__}",
            router_mode="fallback",
        )

    by_catalog = {source.target_id: source for source in shortlist}
    outcome = str(payload.get("outcome") or "").strip().lower()
    selected_id = str(
        payload.get("catalog_id") or payload.get("selected_catalog_id") or ""
    ).strip()
    reason = _compact_text(payload.get("reason"), max_chars=300) or "model_database_route"
    if outcome == "selected" and selected_id in by_catalog:
        return _selected(by_catalog[selected_id], reason=reason, router_mode="ai_assisted")
    candidate_ids = payload.get("candidate_catalog_ids")
    candidates = (
        [
            by_catalog[candidate_id]
            for candidate_id in candidate_ids
            if isinstance(candidate_id, str) and candidate_id in by_catalog
        ]
        if isinstance(candidate_ids, list)
        else []
    )
    if not candidates:
        candidates = shortlist[:3]
    if outcome == "no_match":
        return DatabaseRouteDecision(
            outcome="no_match",
            selected_catalog_id=None,
            candidates=tuple(_candidate(source) for source in candidates),
            reason=reason,
            clarification_question=_compact_text(
                payload.get("clarification_question"), max_chars=300
            ) or None,
            router_mode="ai_assisted",
        )
    return _clarification(
        candidates,
        reason=reason if outcome == "clarification" else "invalid_database_router_output",
        question=_compact_text(payload.get("clarification_question"), max_chars=300)
        or None,
        router_mode="ai_assisted" if outcome == "clarification" else "fallback",
    )


def _routing_score(question: str, source: VisibleQuerySource) -> int:
    query_tokens = set(_tokens(question))
    positive = set(
        _tokens(
            " ".join(
                str(value)
                for key, value in source.routing_card.items()
                if key != "exclusions"
            )
        )
    )
    exclusions = set(
        _tokens(" ".join(str(item) for item in source.routing_card.get("exclusions", [])))
    )
    return len(query_tokens & positive) - (2 * len(query_tokens & exclusions))


def _routing_prompt(question: str, sources: list[VisibleQuerySource]) -> str:
    candidates = [
        {
            "catalog_id": source.target_id,
            "name": source.name,
            "description": source.description or "",
            "routing_profile": source.routing_card,
        }
        for source in sources
    ]
    return (
        "Choose the single database that best covers the user's requested entities and metrics. "
        "Treat exclusions as negative evidence. If two sources define the requested concept or the metadata is insufficient, "
        "return clarification instead of guessing. If none applies, return no_match. "
        "Return JSON with keys outcome, catalog_id, candidate_catalog_ids, reason, and clarification_question. "
        "outcome must be selected, clarification, or no_match. candidate_catalog_ids may contain at most three IDs.\n\n"
        f"User question: {_compact_text(question, max_chars=1000)}\n"
        f"Authorized database candidates: {json.dumps(candidates, ensure_ascii=True)}"
    )


def _selected(
    source: VisibleQuerySource, *, reason: str, router_mode: str = "deterministic"
) -> DatabaseRouteDecision:
    return DatabaseRouteDecision(
        outcome="selected",
        selected_catalog_id=source.target_id,
        candidates=(_candidate(source),),
        reason=reason,
        router_mode=router_mode,
    )


def _clarification(
    sources: list[VisibleQuerySource],
    *,
    reason: str,
    question: str | None = None,
    router_mode: str = "deterministic",
) -> DatabaseRouteDecision:
    candidates = tuple(_candidate(source) for source in sources[:3])
    return DatabaseRouteDecision(
        outcome="clarification",
        selected_catalog_id=None,
        candidates=candidates,
        reason=reason,
        clarification_question=question
        or "Which database source should I use for this question?",
        router_mode=router_mode,
    )


def _candidate(source: VisibleQuerySource) -> DatabaseRouteCandidate:
    return DatabaseRouteCandidate(
        source_id=source.id,
        catalog_id=source.target_id,
        name=source.name,
        description=source.description or "",
    )


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    text = str(value).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match is None:
            raise ValueError("database router did not return a JSON object")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("database router response must be a JSON object")
    return {str(key): item for key, item in payload.items()}


def _tokens(value: object) -> list[str]:
    return [match.group(0).lower() for match in re.finditer(r"[A-Za-z0-9_]{3,}", str(value))]


def _compact_text(value: object, *, max_chars: int) -> str:
    return " ".join(str(value or "").split())[:max_chars].strip()
