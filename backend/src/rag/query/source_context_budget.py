"""Selection of retrieval hits within a bounded context budget."""

from __future__ import annotations

from .qdrant import SearchHit
from .source_mapping import payload_text


def _hits_within_budget(
    hits: list[SearchHit], *, token_budget: int, limit: int
) -> list[SearchHit]:
    selected: list[SearchHit] = []
    used_tokens = 0
    for hit in hits:
        text = payload_text(hit)
        if not text:
            continue
        estimated_tokens = max(1, len(text) // 4)
        if (
            estimated_tokens > token_budget
            or used_tokens + estimated_tokens > token_budget
        ):
            continue
        selected.append(hit)
        used_tokens += estimated_tokens
        if len(selected) >= limit:
            break
    return selected
