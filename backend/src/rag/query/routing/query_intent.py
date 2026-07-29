"""Retry-query compatibility helper."""

from __future__ import annotations

def rewrite_for_retry(query: str, retry_count: int) -> str:
    strategies = (
        "Expand acronyms and retrieve broadly",
        "Broaden to the closest document topic",
        "Remove narrow constraints but keep the original meaning",
    )
    strategy = strategies[min(retry_count, len(strategies) - 1)]
    return f"{strategy}: {query}"
