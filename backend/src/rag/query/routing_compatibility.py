"""Compatibility mapping for frozen public query intent labels."""

from __future__ import annotations

from ..schemas.query import QueryIntent
from .routing_models import public_intent_for as _public_intent_for

_ALIASES = {
    "factual": "factual_simple",
    "conflict": "conflict_check",
    "follow_up": "conversational_followup",
}


def public_intent_for(intent: str) -> QueryIntent:
    return _public_intent_for(_ALIASES.get(intent, intent))  # type: ignore[arg-type]
