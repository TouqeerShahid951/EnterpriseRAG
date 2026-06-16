"""Answer generation application service."""

from __future__ import annotations

from typing import Any

from rag.query.state import QueryContext
from rag.query.synthesis import synthesize_response


class GenerationService:
    """Generate a grounded answer from prepared query evidence."""

    def __init__(self, *, language_model: Any) -> None:
        self._language_model = language_model

    def generate(self, ctx: QueryContext, *, cancellation_token: Any = None) -> QueryContext:
        return synthesize_response(ctx, self._language_model, cancellation_token=cancellation_token)
