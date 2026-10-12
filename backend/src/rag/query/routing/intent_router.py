"""Build a domain-neutral retrieval plan, escalating only uncertain queries."""

from __future__ import annotations

import re
from dataclasses import replace

from rag.query.cancellation import QueryCancellationToken, QueryCancelled
from rag.query.http import ServiceRequestError
from rag.query.retrieval.retrieval_plans import retrieval_settings_for
from rag.query.routing.capability_planner import (
    CapabilityPlanDecision,
    plan_capabilities_with_llm,
)
from rag.query.routing.evidence_planning import (
    INDEXED_CORPUS_SOURCE_ID,
    KNOWLEDGE_GRAPH_SOURCE_ID,
    compile_retrieval_capabilities,
    default_evidence_plan,
)
from rag.query.routing.routing_models import (
    EvidenceNeed,
    EvidencePlan,
    QuerySignals,
    ResponseMode,
    RetrievalCapability,
    RouteIntent,
    RoutePenalty,
    RoutePlan,
    SourceAssignment,
    SummaryMode,
    public_intent_for,
)
from rag.query.routing.routing_signals import extract_query_signals

_NAVIGATION_RE = re.compile(
    r"\b(?:appendix|chapter|citation|clause|heading|pages?|paragraph|sections?)\b"
    r"|\bwhere\s+in\b|\blocat(?:e|ed|ion)\b",
    re.IGNORECASE,
)
_SUMMARY_RE = re.compile(
    r"\bsummari[sz]e\b"
    r"|\b(?:give|provide|create|write|show)\s+(?:me\s+)?(?:a|an|the)?\s*(?:overview|summary)\b"
    r"|\b(?:overview|summary)\s+of\b"
    r"|\bwhat\s+is\s+(?:this|that|the|selected)\s+(?:document|file|report|manual|source)\s+about\b",
    re.IGNORECASE,
)
_NEGATED_SUMMARY_RE = re.compile(
    r"\b(?:do\s+not|don't|dont|not\s+to|without)\s+summari[sz](?:e|ing)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(
    r"\b(?:compare|compared|comparison|contrast|differences?|similarities|versus)\b"
    r"|\bvs\.?\b|\bwhat\s+changed\b|\bchanges?\s+between\b",
    re.IGNORECASE,
)
_CONFLICT_RE = re.compile(
    r"\b(?:conflicts?|contradictions?|disagree|inconsistent|mismatch)\b",
    re.IGNORECASE,
)
_PROCEDURE_RE = re.compile(
    r"\b(?:diagnose|fix|prerequisites?|procedure|rollback|steps?|troubleshoot|workflow)\b"
    r"|\bhow\s+(?:do|can|should|would)\s+(?:i|we|you)\b",
    re.IGNORECASE,
)
_GLOBAL_GRAPH_RE = re.compile(
    r"\b(?:big\s+picture|corpus-wide)\b"
    r"|\b(?:relationships?|themes?)\b.*\bacross\b"
    r"|\bwhat\s+depends\s+on\b",
    re.IGNORECASE,
)
_EXHAUSTIVE_RE = re.compile(
    r"\b(?:all|complete|comprehensive|each|entire|enumerate|every|everything)\b",
    re.IGNORECASE,
)
_CORPUS_SCOPE_RE = re.compile(
    r"\b(?:across|all|entire)\s+(?:the\s+)?(?:corpus|documents?|files?|knowledge\s+base|sources?)\b",
    re.IGNORECASE,
)
_ALL_HISTORY_RE = re.compile(
    r"\b(?:all\s+(?:historical\s+)?versions|entire\s+history|across\s+(?:the\s+)?history)\b",
    re.IGNORECASE,
)
_SCALAR_VALUE_RE = re.compile(r"\b(?:how\s+many|number\s+of)\b", re.IGNORECASE)
_MULTIPART_QUESTION_RE = re.compile(
    r";"
    r"|\band\s+(?:what|who|where|when|which|why|how|does|did|is|are|can|should)\b"
    r"|\band\s+(?:compare|evaluate|explain|find|identify|list|locate|show|summari[sz]e)\b",
    re.IGNORECASE,
)
_CURRENT_ONLY_TEMPORAL_CLUES = {
    "current",
    "currently",
    "latest",
    "still valid",
    "update",
    "updated",
    "valid",
}


def route_query(
    query: str,
    *,
    turns: list[dict[str, object]],
    base_top_k: int,
    llm_verifier: object | None = None,
    verifier_model: str | None = None,
    verifier_enabled: bool = True,
    query_planner_enabled: bool = True,
    cancellation_token: QueryCancellationToken | None = None,
    source_decision: object | None = None,
    source_candidates: dict[str, object] | None = None,
) -> tuple[RoutePlan, QuerySignals]:
    """Build a validated capability plan, falling back to ordinary hybrid search."""

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    signals = extract_query_signals(query, turns)
    operations = _operation_signals(signals.normalized_query)
    baseline = _baseline_capability_plan(
        signals,
        source_decision,
        operations,
        source_candidates=source_candidates,
    )
    decision: CapabilityPlanDecision | None = None
    penalty: RoutePenalty | None = None
    route_method: str | None = None

    if not _needs_capability_planner(
        signals,
        source_decision,
        operations,
        source_candidates=source_candidates,
    ):
        decision = baseline
        route_method = "rules"
    elif verifier_enabled and llm_verifier is not None:
        try:
            decision = plan_capabilities_with_llm(
                llm_verifier,
                model=verifier_model,
                signals=signals,
                source_candidates=source_candidates,
                cancellation_token=cancellation_token,
            )
        except QueryCancelled:
            raise
        except (TypeError, ValueError, RuntimeError, ServiceRequestError) as exc:
            penalty = RoutePenalty(None, f"capability_planner_failed:{type(exc).__name__}", -0.20)

    if decision is None:
        reason = (
            "safe fallback: capability planner failed"
            if penalty is not None
            else "safe fallback: capability planner unavailable"
        )
        decision = replace(baseline, reason=f"{reason}; {baseline.reason}")
        route_method = "fallback"
    elif route_method is None:
        decision = _merge_planner_decision(
            baseline,
            decision,
            operations=operations,
            source_decision=source_decision,
            source_candidates=source_candidates,
        )
        route_method = "llm_planner"

    decision = _normalize_temporal_scope(decision, signals)
    decision = _normalize_evidence_plan(decision, source_decision)
    decision = _normalize_source_capabilities(decision, source_decision)
    decision = _normalize_scalar_lookup(
        decision,
        signals,
        source_decision=source_decision,
    )
    settings = retrieval_settings_for(
        capabilities=decision.capabilities,
        response_mode=decision.response_mode,
        scope=decision.scope,
        coverage=decision.coverage,
        temporal_scope=decision.temporal_scope,
        query=signals.resolved_query,
        base_top_k=base_top_k,
    )
    use_query_planner = bool(settings["use_query_planner"]) and query_planner_enabled
    intent = _compatibility_intent(decision)
    has_planned_evidence_needs = bool(
        decision.evidence_plan is not None
        and len(decision.evidence_plan.needs) > 1
    )
    plan = RoutePlan(
        original_query=signals.original_query,
        resolved_query=signals.resolved_query,
        intent=intent,
        capabilities=decision.capabilities,
        response_mode=decision.response_mode,
        scope=decision.scope,
        coverage=decision.coverage,
        summary_mode=_summary_mode(signals.normalized_query, operations),
        temporal_scope=decision.temporal_scope,
        sub_queries=(
            decision.sub_queries
            if use_query_planner or has_planned_evidence_needs
            else ()
        ),
        evidence_plan=decision.evidence_plan,
        planner_reason=decision.reason,
        confidence=0.0,
        route_method=route_method,  # type: ignore[arg-type]
        needs_retrieval=bool(settings["needs_retrieval"]),
        retrieval_strategy=str(settings["retrieval_strategy"]),
        search_mode=settings["search_mode"],  # type: ignore[arg-type]
        use_query_planner=use_query_planner,
        use_reranker=bool(settings["use_reranker"]),
        use_conversation_memory=signals.use_conversation_memory,
        use_temporal_filter=bool(settings["use_temporal_filter"]),
        use_conflict_checker=bool(settings["use_conflict_checker"]),
        use_structured_query=bool(settings["use_structured_query"]),
        chunk_granularity=settings["chunk_granularity"],  # type: ignore[arg-type]
        top_k=max(
            int(settings["top_k"]),
            50
            if _summary_mode(signals.normalized_query, operations) == "topic"
            else 1,
        ),
        filters=dict(settings["filters"]),
        allow_abstain=bool(settings["allow_abstain"]),
        risk_level=settings["risk_level"],  # type: ignore[arg-type]
        debug_reason=decision.reason,
        penalties=(penalty,) if penalty is not None else (),
        public_intent=public_intent_for(intent),
    )
    return plan, signals


def _needs_capability_planner(
    signals: QuerySignals,
    source_decision: object | None,
    operations: frozenset[str],
    *,
    source_candidates: dict[str, object] | None = None,
) -> bool:
    if _clear_document_lookup_source_id(
        signals,
        source_decision,
        operations,
        source_candidates,
    ):
        return False
    if _MULTIPART_QUESTION_RE.search(signals.normalized_query):
        return True
    response_operations = operations & {
        "comparison",
        "conflict",
        "global_graph",
        "navigation",
        "procedure",
        "summary",
    }
    compatible_comparison = response_operations <= {"comparison", "conflict"}
    if len(response_operations) > 1 and not compatible_comparison:
        return True
    if signals.is_short_query and (
        operations
        or any(clue not in _CURRENT_ONLY_TEMPORAL_CLUES for clue in signals.temporal_clues)
    ):
        return True
    if _requires_hybrid_sources(source_decision):
        return True
    database_candidates = (source_candidates or {}).get("databases")
    if (
        source_decision is not None
        and not bool(getattr(source_decision, "explicit", False))
        and isinstance(database_candidates, list)
        and bool(database_candidates)
    ):
        return True
    return bool(
        source_decision is not None
        and not bool(getattr(source_decision, "explicit", False))
        and _has_database_route_signal(source_decision)
    )


def _operation_signals(normalized_query: str) -> frozenset[str]:
    patterns = {
        "navigation": _NAVIGATION_RE,
        "summary": _SUMMARY_RE,
        "comparison": _COMPARISON_RE,
        "conflict": _CONFLICT_RE,
        "procedure": _PROCEDURE_RE,
        "global_graph": _GLOBAL_GRAPH_RE,
        "exhaustive": _EXHAUSTIVE_RE,
    }
    operations = {
        operation
        for operation, pattern in patterns.items()
        if pattern.search(normalized_query)
    }
    if _NEGATED_SUMMARY_RE.search(normalized_query):
        operations.discard("summary")
    return frozenset(operations)


def _baseline_capability_plan(
    signals: QuerySignals,
    source_decision: object | None,
    operations: frozenset[str],
    *,
    source_candidates: dict[str, object] | None,
) -> CapabilityPlanDecision:
    source_mode = str(getattr(source_decision, "resolved_mode", "") or "")
    database_selected = source_mode in {"db_only", "db_first"}
    use_live_sql = (
        database_selected
        or _has_database_route_signal(source_decision)
        or _requires_hybrid_sources(source_decision)
    )
    capabilities = ["general_search"]
    if use_live_sql:
        capabilities.append("live_sql")
    elif "global_graph" in operations and _graph_available(source_candidates):
        capabilities.append("global_graph")
    if not database_selected and "navigation" in operations:
        capabilities.append("document_navigation")
    if not database_selected and "summary" in operations:
        capabilities.append("document_search")
    if operations & {"comparison", "conflict"}:
        capabilities.append("decomposed_search")
    capabilities = list(dict.fromkeys(capabilities))[:4]

    response_mode = _required_response_mode(operations) or "lookup"

    summary_mode = _summary_mode(signals.normalized_query, operations)
    document_summary = summary_mode in {"document", "section", "multi_document"}
    coverage = (
        "exhaustive"
        if "exhaustive" in operations or document_summary
        else "focused"
    )
    document_source_id = _clear_document_lookup_source_id(
        signals,
        source_decision,
        operations,
        source_candidates,
    )
    document_selected = (
        getattr(source_decision, "reason", None) == "document_scope_selected"
        or bool(document_source_id)
        or summary_mode in {"document", "section"}
    )
    if summary_mode == "topic" and not document_selected:
        scope = "corpus"
    elif (
        use_live_sql
        or "global_graph" in operations
        or _CORPUS_SCOPE_RE.search(signals.normalized_query)
        or (coverage == "exhaustive" and not document_selected)
    ):
        scope = "corpus"
    elif operations & {"navigation", "summary"} or document_selected:
        scope = "document"
    else:
        scope = "local"

    temporal_scope = _deterministic_temporal_scope(signals)
    reasons = sorted(operations) or ["ordinary_lookup"]
    if use_live_sql:
        reasons.append("live_sql")
    if temporal_scope != "current":
        reasons.append(f"temporal_{temporal_scope}")
    evidence_plan = default_evidence_plan(
        signals.resolved_query,
        source_decision=source_decision,
    )
    if document_source_id:
        need = evidence_plan.needs[0]
        evidence_plan = EvidencePlan(
            needs=(
                replace(
                    need,
                    assignments=(
                        SourceAssignment(
                            source_id=document_source_id,
                            capability="indexed_search",
                        ),
                    ),
                ),
            )
        )
    if "global_graph" in capabilities:
        need = evidence_plan.needs[0]
        evidence_plan = EvidencePlan(
            needs=(
                replace(
                    need,
                    assignments=(
                        *need.assignments,
                        SourceAssignment(
                            source_id=KNOWLEDGE_GRAPH_SOURCE_ID,
                            capability="graph_query",
                        ),
                    ),
                ),
            )
        )
    return CapabilityPlanDecision(
        capabilities=tuple(capabilities),  # type: ignore[arg-type]
        response_mode=response_mode,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
        coverage=coverage,  # type: ignore[arg-type]
        temporal_scope=temporal_scope,  # type: ignore[arg-type]
        evidence_plan=evidence_plan,
        reason=f"deterministic capability route: {','.join(reasons)}",
    )


def _clear_document_lookup_source_id(
    signals: QuerySignals,
    source_decision: object | None,
    operations: frozenset[str],
    source_candidates: dict[str, object] | None,
) -> str | None:
    summary_request = _requires_document_summary_coverage(
        signals.normalized_query, operations
    )
    scalar_request = _SCALAR_VALUE_RE.search(signals.normalized_query) is not None
    if (
        not summary_request and not scalar_request
        or (summary_request and operations != {"summary"})
        or (not summary_request and operations - {"exhaustive"})
        or _requires_hybrid_sources(source_decision)
        or getattr(source_decision, "preferred_source", None) != "corpus"
        or int(getattr(source_decision, "document_match_score", 0) or 0)
        < (1 if summary_request else 2)
    ):
        return None
    documents = [
        item
        for item in (source_candidates or {}).get("documents", [])
        if isinstance(item, dict)
        and item.get("source_id")
        and int(item.get("score", 0) or 0) >= (1 if summary_request else 2)
    ]
    if not documents:
        return None
    best_score = max(int(item.get("score", 0) or 0) for item in documents)
    matches = [item for item in documents if int(item.get("score", 0) or 0) == best_score]
    return str(matches[0]["source_id"]) if len(matches) == 1 else None


def _requires_document_summary_coverage(
    query: str, operations: frozenset[str]
) -> bool:
    """Require every section for a broad summary of one document."""

    return _summary_mode(query, operations) == "document"


def _summary_mode(query: str, operations: frozenset[str]) -> SummaryMode | None:
    if "summary" not in operations:
        return None
    if "comparison" in operations:
        return "multi_document"
    if _NAVIGATION_RE.search(query):
        return "section"
    if re.search(
        r"\b(?:document|file|manual|report|source)\b|\b(?:this|that|selected)\s+one\b",
        query,
        re.IGNORECASE,
    ) or not re.search(r"\b(?:about|of|on|regarding|related\s+to)\b", query):
        summary_tail = re.sub(_SUMMARY_RE, "", query).strip(" .?!")
        if not summary_tail or summary_tail.lower() in {"this", "that", "it"}:
            return "document"
        if re.search(r"\b(?:document|file|manual|report|source)\b", summary_tail):
            return "document"
        if re.match(r"^(?:this|that|the|selected)\b", summary_tail, re.IGNORECASE):
            return "document"
    return "topic"


def _merge_planner_decision(
    baseline: CapabilityPlanDecision,
    planned: CapabilityPlanDecision,
    *,
    operations: frozenset[str],
    source_decision: object | None,
    source_candidates: dict[str, object] | None,
) -> CapabilityPlanDecision:
    """Let AI refine a plan without removing explicit deterministic requirements."""

    required_capabilities = _required_capabilities(
        operations,
        source_decision,
        source_candidates=source_candidates,
    )
    optional_capabilities = [
        capability
        for capability in planned.capabilities
        if capability not in required_capabilities
    ]
    optional_limit = max(0, 4 - len(required_capabilities))
    capabilities = (
        *required_capabilities,
        *optional_capabilities[:optional_limit],
    )
    required_response_mode = _required_response_mode(operations)
    response_mode = required_response_mode or planned.response_mode
    coverage = (
        "exhaustive"
        if baseline.coverage == "exhaustive"
        else planned.coverage
    )
    temporal_scope = (
        baseline.temporal_scope
        if baseline.temporal_scope != "current"
        else planned.temporal_scope
    )
    document_selected = (
        getattr(source_decision, "reason", None) == "document_scope_selected"
    )
    scope = (
        baseline.scope
        if coverage == "exhaustive"
        or "global_graph" in operations
        or document_selected
        else planned.scope
    )
    preserved: list[str] = []
    if capabilities != planned.capabilities:
        preserved.append("capabilities")
    if response_mode != planned.response_mode:
        preserved.append("response_mode")
    if scope != planned.scope:
        preserved.append("scope")
    if coverage != planned.coverage:
        preserved.append("coverage")
    if temporal_scope != planned.temporal_scope:
        preserved.append("temporal_scope")
    if not preserved:
        return (
            planned
            if planned.evidence_plan is not None
            else replace(planned, evidence_plan=baseline.evidence_plan)
        )
    reason = (
        f"{planned.reason}; preserved deterministic "
        f"{','.join(preserved)}"
    )[:300]
    return replace(
        planned,
        capabilities=capabilities,
        response_mode=response_mode,
        scope=scope,
        coverage=coverage,
        temporal_scope=temporal_scope,
        evidence_plan=planned.evidence_plan or baseline.evidence_plan,
        reason=reason,
    )


def _required_capabilities(
    operations: frozenset[str],
    source_decision: object | None,
    *,
    source_candidates: dict[str, object] | None,
) -> tuple[RetrievalCapability, ...]:
    source_mode = str(getattr(source_decision, "resolved_mode", "") or "")
    database_selected = source_mode in {"db_only", "db_first"}
    capabilities: list[RetrievalCapability] = ["general_search"]
    if database_selected or _requires_hybrid_sources(source_decision):
        capabilities.append("live_sql")
    if operations & {"comparison", "conflict"}:
        capabilities.append("decomposed_search")
    if not database_selected and "navigation" in operations:
        capabilities.append("document_navigation")
    if not database_selected and "summary" in operations:
        capabilities.append("document_search")
    if (
        not database_selected
        and "global_graph" in operations
        and _graph_available(source_candidates)
    ):
        capabilities.append("global_graph")
    return tuple(capabilities)


def _graph_available(source_candidates: dict[str, object] | None) -> bool:
    if source_candidates is None:
        return True
    graphs = source_candidates.get("graphs")
    return isinstance(graphs, list) and any(
        isinstance(source, dict)
        and "graph_query" in source.get("methods", [])
        for source in graphs
    )


def _required_response_mode(
    operations: frozenset[str],
) -> ResponseMode | None:
    if "conflict" in operations:
        return "conflict_analysis"
    if "comparison" in operations:
        return "comparison"
    if "summary" in operations:
        return "summary"
    if "procedure" in operations:
        return "procedure"
    if "global_graph" in operations:
        return "explanation"
    return None


def _has_database_route_signal(source_decision: object | None) -> bool:
    if source_decision is None:
        return False
    source_mode = str(getattr(source_decision, "resolved_mode", "") or "")
    if source_mode == "corpus_only":
        return False
    if source_mode in {"db_only", "db_first"}:
        return True
    return bool(
        getattr(source_decision, "preferred_source", None) == "database"
        and (
            int(getattr(source_decision, "structured_score", 0) or 0) > 0
            or int(getattr(source_decision, "source_match_score", 0) or 0) > 0
        )
    )


def _requires_hybrid_sources(source_decision: object | None) -> bool:
    """Retain both branches when corpus and database evidence are both required."""

    if source_decision is None:
        return False
    return bool(
        getattr(source_decision, "resolved_mode", None) == "hybrid"
        and (
            getattr(source_decision, "query_source_record_id", None)
            or getattr(source_decision, "preferred_catalog_id", None)
        )
        and int(getattr(source_decision, "corpus_score", 0) or 0) > 0
        and (
            int(getattr(source_decision, "structured_score", 0) or 0) > 0
            or int(getattr(source_decision, "source_match_score", 0) or 0) > 0
        )
    )


def _deterministic_temporal_scope(signals: QuerySignals) -> str:
    if _ALL_HISTORY_RE.search(signals.normalized_query):
        return "all"
    if "as of" in signals.temporal_clues:
        return "as_of"
    if any(clue not in _CURRENT_ONLY_TEMPORAL_CLUES for clue in signals.temporal_clues):
        return "historical"
    return "current"


def _normalize_temporal_scope(
    decision: CapabilityPlanDecision,
    signals: QuerySignals,
) -> CapabilityPlanDecision:
    """Require a query-side temporal signal before enabling historical semantics."""

    if decision.temporal_scope == "current" or signals.temporal_clues:
        return decision
    return replace(decision, temporal_scope="current")


def _normalize_evidence_plan(
    decision: CapabilityPlanDecision,
    source_decision: object | None,
) -> CapabilityPlanDecision:
    """Validate planner assignments against an explicit source boundary."""

    plan = decision.evidence_plan or default_evidence_plan(
        " ".join(decision.sub_queries).strip() or "retrieval request",
        source_decision=source_decision,
    )
    mode = str(getattr(source_decision, "resolved_mode", "") or "")
    explicit = bool(getattr(source_decision, "explicit", False))
    selected_source_ids = tuple(
        str(item)
        for item in getattr(source_decision, "query_source_ids", ())
        if str(item)
    )
    selected_source_id = str(getattr(source_decision, "query_source_id", "") or "")
    if not selected_source_ids and selected_source_id:
        selected_source_ids = (selected_source_id,)
    selected_source_set = set(selected_source_ids)
    normalized_needs: list[EvidenceNeed] = []
    for need in plan.needs:
        assignments = list(need.assignments)
        if explicit and mode == "corpus_only":
            assignments = [
                item for item in assignments if item.capability == "indexed_search"
            ]
        elif explicit and mode in {"db_only", "db_first"}:
            assignments = [
                item
                for item in assignments
                if item.capability == "connector_query"
                and (not selected_source_set or item.source_id in selected_source_set)
            ]
        elif explicit and mode == "hybrid" and selected_source_set:
            assignments = [
                item
                for item in assignments
                if item.capability != "connector_query"
                or item.source_id in selected_source_set
            ]
        assigned_connector_ids = {
            item.source_id
            for item in assignments
            if item.capability == "connector_query"
        }
        if explicit and mode in {"db_only", "db_first", "hybrid"}:
            assignments.extend(
                SourceAssignment(
                    source_id=source_id,
                    capability="connector_query",
                )
                for source_id in selected_source_ids
                if source_id not in assigned_connector_ids
            )
        if not assignments:
            if explicit and mode in {"db_only", "db_first"} and selected_source_ids:
                assignments = [
                    SourceAssignment(
                        source_id=source_id,
                        capability="connector_query",
                    )
                    for source_id in selected_source_ids
                ]
            else:
                assignments = [
                    SourceAssignment(
                        source_id=INDEXED_CORPUS_SOURCE_ID,
                        capability="indexed_search",
                    )
                ]
        normalized_needs.append(replace(need, assignments=tuple(assignments)))
    normalized_plan = EvidencePlan(needs=tuple(normalized_needs))
    capabilities = compile_retrieval_capabilities(
        decision.capabilities, normalized_plan
    )
    sub_queries = decision.sub_queries
    if len(normalized_plan.needs) > 1 and not sub_queries:
        sub_queries = tuple(need.query for need in normalized_plan.needs)
    return replace(
        decision,
        capabilities=capabilities,
        sub_queries=sub_queries,
        evidence_plan=normalized_plan,
    )


def _normalize_source_capabilities(
    decision: CapabilityPlanDecision,
    source_decision: object | None,
) -> CapabilityPlanDecision:
    """Keep planner output inside the source boundary selected before routing."""

    source_mode = getattr(source_decision, "resolved_mode", None)
    if source_mode == "corpus_only" and "live_sql" in decision.capabilities:
        return replace(
            decision,
            capabilities=tuple(
                capability
                for capability in decision.capabilities
                if capability != "live_sql"
            ),
        )
    if source_mode in {"db_only", "db_first"}:
        capabilities = tuple(decision.capabilities)
        if "live_sql" not in capabilities:
            capabilities = (*capabilities[:3], "live_sql")
        return replace(
            decision,
            capabilities=capabilities,  # type: ignore[arg-type]
            scope="corpus",
        )
    return decision


def _normalize_scalar_lookup(
    decision: CapabilityPlanDecision,
    signals: QuerySignals,
    *,
    source_decision: object | None,
) -> CapabilityPlanDecision:
    """Keep a focused scalar fact request from expanding into a summary."""

    if (
        _requires_hybrid_sources(source_decision)
        or (
            decision.evidence_plan is not None
            and len(decision.evidence_plan.needs) > 1
        )
        or decision.response_mode not in {"lookup", "summary", "explanation"}
        or not set(decision.capabilities).issubset(
            {"general_search", "decomposed_search"}
        )
        or decision.coverage != "focused"
        or not _SCALAR_VALUE_RE.search(signals.normalized_query)
        or _SUMMARY_RE.search(signals.normalized_query)
        or _MULTIPART_QUESTION_RE.search(signals.normalized_query)
    ):
        return decision
    return replace(
        decision,
        capabilities=("general_search",),
        response_mode="lookup",
        sub_queries=(),
    )


def _compatibility_intent(decision: CapabilityPlanDecision) -> RouteIntent:
    """Map the typed plan onto the public and legacy execution vocabulary."""

    if decision.temporal_scope != "current":
        return "temporal_comparison" if decision.response_mode == "comparison" else "temporal_factual"
    if decision.response_mode == "conflict_analysis":
        return "conflict_check"
    if "global_graph" in decision.capabilities:
        return "graphrag_global"
    if "document_navigation" in decision.capabilities:
        return "document_navigation"
    if decision.response_mode == "comparison":
        return "comparison"
    if decision.response_mode == "procedure":
        return "procedural"
    if decision.response_mode == "summary":
        return "summarization"
    if "decomposed_search" in decision.capabilities:
        return "multi_hop"
    if (
        decision.coverage == "exhaustive"
        and set(decision.capabilities) & {"structured_query", "live_sql"}
    ):
        return "aggregation"
    return "general_rag"
