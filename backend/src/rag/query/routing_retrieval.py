"""Compatibility retrieval profile helpers for router tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalPlanProfile:
    strategy: str
    current_only: bool = True
    include_superseded: bool = False
    requires_conflict_lookup: bool = False
    requires_summary_synthesis: bool = False
    sub_query_limit: int = 1


def retrieval_plan_for_intent(intent: str) -> RetrievalPlanProfile:
    normalized = {
        "factual_simple": "factual",
        "conflict_check": "conflict",
        "conversational_followup": "follow_up",
    }.get(intent, intent)
    profiles = {
        "factual": RetrievalPlanProfile("single_pass"),
        "procedural": RetrievalPlanProfile("ordered_steps"),
        "summarization": RetrievalPlanProfile("broad_summary", requires_summary_synthesis=True),
        "comparison": RetrievalPlanProfile("parallel_compare", sub_query_limit=2),
        "aggregation": RetrievalPlanProfile("aggregate"),
        "conflict": RetrievalPlanProfile("conflict_probe", requires_conflict_lookup=True),
        "document_navigation": RetrievalPlanProfile("document_navigation"),
        "follow_up": RetrievalPlanProfile("contextual_follow_up"),
        "temporal_comparison": RetrievalPlanProfile(
            "temporal_comparison",
            current_only=False,
            include_superseded=True,
            sub_query_limit=2,
        ),
        "comparative_summary": RetrievalPlanProfile(
            "comparative_summary",
            requires_summary_synthesis=True,
            sub_query_limit=2,
        ),
    }
    return profiles.get(normalized, RetrievalPlanProfile("single_pass"))
