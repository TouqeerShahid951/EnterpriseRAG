"""Post-retrieval evidence inspection for route correction."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .qdrant import SearchHit
from .routing_models import RoutePlan


@dataclass(frozen=True)
class EvidenceInspection:
    should_reroute: bool
    reason: str | None = None
    next_plan: RoutePlan | None = None


def inspect_evidence_for_reroute(plan: RoutePlan, hits: list[SearchHit], *, reroute_count: int) -> EvidenceInspection:
    if reroute_count >= 1 or not hits:
        return EvidenceInspection(False)
    if plan.intent in {"comparison", "temporal_comparison", "comparative_summary"} and _comparison_side_coverage(plan, hits) < 2:
        return EvidenceInspection(
            True,
            reason="comparison_evidence_covered_one_side",
            next_plan=_general_rag_reroute(plan),
        )
    if (
        plan.intent == "aggregation"
        and plan.use_structured_query
        and not any(_has_table_evidence(hit) for hit in hits)
        and not any(_has_exhaustive_scope_evidence(hit) for hit in hits)
    ):
        return EvidenceInspection(
            True,
            reason="aggregation_without_structured_evidence",
            next_plan=_general_rag_reroute(plan),
        )
    if plan.intent == "document_navigation" and not any(_has_source_metadata(hit) for hit in hits):
        return EvidenceInspection(
            True,
            reason="document_navigation_without_source_metadata",
            next_plan=_general_rag_reroute(plan),
        )
    if plan.intent == "conflict_check" and plan.use_conflict_checker and not any(_has_claim_evidence(hit) for hit in hits):
        return EvidenceInspection(
            True,
            reason="conflict_route_without_claim_evidence",
            next_plan=_general_rag_reroute(plan),
        )
    max_score = max((hit.score for hit in hits), default=0.0)
    if max_score >= 0.6:
        return EvidenceInspection(False)
    return EvidenceInspection(False)


def _comparison_side_coverage(plan: RoutePlan, hits: list[SearchHit]) -> int:
    terms = [
        term
        for term in plan.resolved_query.lower().replace("versus", " ").replace("compare", " ").split()
        if len(term) >= 4
    ]
    if not terms:
        return 0
    text = " ".join(str(hit.payload.get("text", "")).lower() for hit in hits)
    return min(2, sum(1 for term in set(terms[:8]) if term in text))


def _general_rag_reroute(plan: RoutePlan) -> RoutePlan:
    return replace(
        plan,
        intent="general_rag",
        secondary_intents=(plan.intent, *plan.secondary_intents),
        route_method="fallback",
        retrieval_strategy="hybrid_reranked",
        search_mode="hybrid",
        use_query_planner=False,
        use_conflict_checker=False,
        use_structured_query=False,
        chunk_granularity="medium",
        debug_reason=f"post-retrieval reroute from {plan.intent}: {plan.debug_reason}",
        public_intent="factual_simple",
    )


def _has_table_evidence(hit: SearchHit) -> bool:
    table_json = hit.payload.get("table_json")
    return isinstance(table_json, dict) and bool(table_json)


def _has_exhaustive_scope_evidence(hit: SearchHit) -> bool:
    return str(hit.payload.get("exhaustive_scope_origin", "")) == "document_class_scope"


def _has_claim_evidence(hit: SearchHit) -> bool:
    claims = hit.payload.get("claims")
    claim_ids = hit.payload.get("claim_ids")
    return (
        bool(hit.payload.get("has_conflict"))
        or (isinstance(claims, list) and bool(claims))
        or (isinstance(claim_ids, list) and bool(claim_ids))
    )


def _has_source_metadata(hit: SearchHit) -> bool:
    return any(
        hit.payload.get(field) not in (None, "", [])
        for field in ("page", "page_start", "page_end", "section_path", "parent_section_id")
    )
