"""Shared latency budget helpers for exhaustive retrieval."""

from __future__ import annotations

from time import monotonic, perf_counter

EXHAUSTIVE_RETRIEVAL_BUDGET_SECONDS = 30.0


def exhaustive_retrieval_deadline(started: float) -> float:
    elapsed = max(0.0, perf_counter() - started) if started > 0 else 0.0
    remaining = max(0.0, EXHAUSTIVE_RETRIEVAL_BUDGET_SECONDS - elapsed)
    return monotonic() + remaining
