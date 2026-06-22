"""Internal data contracts for query intent routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..schemas.query import QueryIntent

RouteIntent = Literal[
    "factual_simple",
    "procedural",
    "summarization",
    "comparison",
    "temporal",
    "temporal_comparison",
    "multi_hop",
    "aggregation",
    "graphrag_global",
    "conflict_check",
    "troubleshooting",
    "document_navigation",
    "conversational_followup",
    "out_of_scope",
    "general_rag",
    "troubleshooting_procedure",
    "comparative_summary",
    "temporal_factual",
]
RouteMethod = Literal["rules", "llm_verifier", "fallback"]
SearchMode = Literal["hybrid", "multi_query_hybrid", "metadata", "structured_first"]
ChunkGranularity = Literal["small", "medium", "section", "document"]
RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class RuleHit:
    intent: RouteIntent
    signal: str
    weight: float
    strength: Literal["strong", "medium", "weak", "bonus"]
    matched_text: str


@dataclass(frozen=True)
class RoutePenalty:
    intent: RouteIntent | None
    reason: str
    weight: float


@dataclass(frozen=True)
class QuerySignals:
    original_query: str
    normalized_query: str
    resolved_query: str
    tokens: tuple[str, ...]
    domain_entity_clues: tuple[str, ...] = ()
    temporal_clues: tuple[str, ...] = ()
    followup_clues: tuple[str, ...] = ()
    has_session_context: bool = False
    use_conversation_memory: bool = False
    is_short_query: bool = False
    is_vague_followup: bool = False
    clarity_bonus: bool = False


@dataclass(frozen=True)
class RuleRouteResult:
    intent: RouteIntent
    secondary_intents: tuple[RouteIntent, ...]
    confidence: float
    margin: float
    raw_scores: dict[RouteIntent, float]
    rule_hits: tuple[RuleHit, ...]
    penalties: tuple[RoutePenalty, ...]
    debug_reason: str


@dataclass(frozen=True)
class RoutePlan:
    original_query: str
    resolved_query: str
    intent: RouteIntent
    secondary_intents: tuple[RouteIntent, ...] = ()
    confidence: float = 0.0
    route_method: RouteMethod = "rules"
    needs_retrieval: bool = True
    retrieval_strategy: str = "hybrid_reranked"
    search_mode: SearchMode = "hybrid"
    use_query_planner: bool = False
    use_reranker: bool = True
    use_conversation_memory: bool = False
    use_temporal_filter: bool = False
    use_conflict_checker: bool = False
    use_structured_query: bool = False
    chunk_granularity: ChunkGranularity = "medium"
    top_k: int = 4
    filters: dict[str, object] = field(default_factory=dict)
    allow_abstain: bool = True
    risk_level: RiskLevel = "low"
    debug_reason: str = ""
    rule_hits: tuple[RuleHit, ...] = ()
    penalties: tuple[RoutePenalty, ...] = ()
    public_intent: QueryIntent = "factual_simple"
    margin: float = 0.0


def public_intent_for(intent: RouteIntent) -> QueryIntent:
    if intent in {"temporal", "temporal_comparison", "temporal_factual"}:
        return "temporal"
    if intent in {"aggregation", "graphrag_global"}:
        return "aggregation"
    if intent in {"conflict_check"}:
        return "contradictory"
    if intent in {"conversational_followup"}:
        return "conversational"
    if intent in {
        "comparison",
        "procedural",
        "summarization",
        "multi_hop",
        "troubleshooting",
        "troubleshooting_procedure",
        "comparative_summary",
    }:
        return "multi_hop"
    return "factual_simple"
