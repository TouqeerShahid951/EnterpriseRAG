"""Query-source decision orchestration and compatibility exports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from rag.connectors.repositories import ConnectorProfileRepository
from rag.documents.models import DocumentRepository
from rag.ingestion.folders.models import FolderScheduleRepository
from rag.query.sources.source_catalog import (
    QuerySourceAccessError as QuerySourceAccessError,
    QuerySourceTargetKind as QuerySourceTargetKind,
    VisibleDocumentSource as VisibleDocumentSource,
    VisibleQuerySource as VisibleQuerySource,
    _SOURCE_PREFIXES as _SOURCE_PREFIXES,
    _SUPPORTED_SQL_CONNECTOR_TYPES as _SUPPORTED_SQL_CONNECTOR_TYPES,
    _catalog_match_text as _catalog_match_text,
    _catalog_name as _catalog_name,
    _catalog_visible as _catalog_visible,
    _current_schema_catalogs as _current_schema_catalogs,
    _document_match_text as _document_match_text,
    _document_visible as _document_visible,
    _optional_str as _optional_str,
    _source_from_catalog as _source_from_catalog,
    list_visible_document_sources as list_visible_document_sources,
    list_visible_query_sources as list_visible_query_sources,
    parse_query_source_id as parse_query_source_id,
    public_query_source as public_query_source,
    query_source_id_for_catalog as query_source_id_for_catalog,
    validate_query_source_access as validate_query_source_access,
)
from rag.query.sources.source_matching import (
    PreferredSource as PreferredSource,
    _CORPUS_DIRECTIVE_RE as _CORPUS_DIRECTIVE_RE,
    _CORPUS_TERMS as _CORPUS_TERMS,
    _DB_DIRECTIVE_RE as _DB_DIRECTIVE_RE,
    _STRUCTURED_TERMS as _STRUCTURED_TERMS,
    _SourcePreference as _SourcePreference,
    _best_scored_source as _best_scored_source,
    _compact_query as _compact_query,
    _conversation_source_bias as _conversation_source_bias,
    _deterministic_preference as _deterministic_preference,
    _document_match_score as _document_match_score,
    _inline_named_source as _inline_named_source,
    _normalize as _normalize,
    _requires_mixed_sources as _requires_mixed_sources,
    _source_match_score as _source_match_score,
    _strip_named_source as _strip_named_source,
    _strip_source_directive as _strip_source_directive,
    _structured_score as _structured_score,
    _term_score as _term_score,
    _tokens as _tokens,
)
from rag.query.sources.database_router import (
    DatabaseRouteDecision,
    route_database_source,
)
from rag.query.state import QueryContext, active_query, scoped_user_context
from rag.query.routing.routing_models import EvidencePlan

ResolvedSourceMode = Literal["corpus_only", "db_only", "db_first", "corpus_first", "hybrid"]


@dataclass(frozen=True)
class SourceDecision:
    requested_mode: str
    resolved_mode: ResolvedSourceMode
    semantic_query: str
    explicit: bool
    reason: str
    directive: str | None = None
    query_source_id: str | None = None
    query_source_ids: tuple[str, ...] = ()
    query_source_kind: QuerySourceTargetKind | None = None
    query_source_record_id: str | None = None
    query_source_record_ids: tuple[str, ...] = ()
    allow_source_expansion: bool = False
    structured_score: int = 0
    corpus_score: int = 0
    source_match_score: int = 0
    document_match_score: int = 0
    preferred_source: PreferredSource = "balanced"
    preferred_catalog_id: str | None = None
    routing_confidence: float = 0.0
    router_mode: str = "deterministic"
    signal_reason: str = ""
    database_route: DatabaseRouteDecision | None = None
    inherited_document_ids: tuple[str, ...] = ()


def resolve_query_source(
    ctx: QueryContext,
    *,
    schedule_repo: FolderScheduleRepository | None = None,
    connector_profile_repo: ConnectorProfileRepository | None = None,
    document_repo: DocumentRepository | None = None,
    graph_enabled: bool = False,
    router_client: object | None = None,
    router_model: str | None = None,
    cancellation_token: object | None = None,
) -> SourceDecision:
    request = ctx["request"]
    user = scoped_user_context(ctx)
    sources = list_visible_query_sources(
        user,
        schedule_repo=schedule_repo,
        connector_profile_repo=connector_profile_repo,
    )
    documents = list_visible_document_sources(user, document_repo=document_repo)
    selected_sources = tuple(
        source
        for source_id in request.effective_query_source_ids
        if (
            source := validate_query_source_access(
                source_id=source_id,
                user=user,
                schedule_repo=schedule_repo,
                connector_profile_repo=connector_profile_repo,
            )
        )
    )
    selected = selected_sources[0] if selected_sources else None
    query_after_directives, directive = _strip_source_directive(active_query(ctx))
    inline_source = selected if selected is not None else _inline_named_source(query_after_directives, sources)
    if selected is None and inline_source is not None:
        query_after_directives = _strip_named_source(query_after_directives, inline_source)
    structured_score = _structured_score(query_after_directives)
    corpus_score = _term_score(query_after_directives, _CORPUS_TERMS)
    source_scores = [(source, _source_match_score(query_after_directives, source)) for source in sources]
    source_match_score = max((score for _source, score in source_scores), default=0)
    preferred_source_record = _best_scored_source(source_scores)
    document_scores = [
        (document, _document_match_score(query_after_directives, document))
        for document in documents
    ]
    document_match_score = max((score for _document, score in document_scores), default=0)
    planner_candidates = _planner_source_candidates(
        source_scores=source_scores,
        document_scores=document_scores,
        graph_enabled=graph_enabled,
    )
    ctx["source_candidates"] = _scope_planner_source_candidates(
        planner_candidates,
        requested_mode=request.source_mode,
        selected_source_ids=(
            tuple(source.id for source in selected_sources)
            if selected_sources
            else (inline_source.id,) if inline_source is not None else ()
        ),
        directive=directive,
        document_ids=tuple(request.document_ids),
    )
    db_bias, corpus_bias = _conversation_source_bias(ctx.get("session_turns", []))
    resolution = ctx.get("conversation_resolution")
    followup = resolution is not None and resolution.relation == "follow_up"
    inherit_exact_source = followup and bool(
        set(resolution.dependency_targets) & {"source", "result"}
    )
    inherited_document_ids = (
        _followup_document_ids(
            ctx.get("session_turns", []),
            resolution.antecedent_turn_ids,
            documents,
        )
        if followup and "source" in resolution.dependency_targets
        else ()
    )
    inherited_sources, inherited_mode = _followup_database_sources(
        ctx.get("session_turns", []), resolution.antecedent_turn_ids, sources
    ) if inherit_exact_source else ((), None)
    preference = _deterministic_preference(
        structured_score=structured_score,
        corpus_score=corpus_score,
        source_match_score=source_match_score,
        document_match_score=document_match_score,
        db_bias=db_bias if followup else 0,
        corpus_bias=corpus_bias if followup else 0,
    )
    if request.source_mode == "corpus_only":
        return _decision(
            request.source_mode,
            "corpus_only",
            query_after_directives,
            explicit=True,
            reason="composer_selected_corpus",
            source=selected,
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="corpus",
            routing_confidence=1.0,
            signal_reason="explicit_corpus_mode",
        )
    if (
        request.source_mode == "auto"
        and selected is None
        and inline_source is None
        and directive is None
        and not request.document_ids
        and inherited_document_ids
    ):
        return _decision(
            request.source_mode,
            "corpus_only",
            query_after_directives,
            explicit=False,
            reason="session_document_source",
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="corpus",
            routing_confidence=1.0,
            signal_reason="followup_document_source",
            inherited_document_ids=inherited_document_ids,
        )
    if (
        selected is None
        and inline_source is None
        and inherited_sources
        and directive != "corpus"
        and not request.document_ids
        and request.source_mode in {"auto", "db_only", "hybrid"}
    ):
        resolved_mode: ResolvedSourceMode = (
            "hybrid"
            if request.source_mode == "hybrid"
            or (request.source_mode == "auto" and inherited_mode == "hybrid")
            else "db_only"
        )
        return _decision(
            request.source_mode,
            resolved_mode,
            query_after_directives,
            explicit=False,
            reason="session_database_source",
            source=inherited_sources[0],
            sources=inherited_sources,
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="database",
            preferred_catalog_id=inherited_sources[0].target_id,
            routing_confidence=1.0,
            signal_reason="followup_database_source",
        )
    if request.source_mode == "db_only" and selected is None:
        return _routed_database_decision(
            requested_mode=request.source_mode,
            resolved_mode="db_only",
            semantic_query=query_after_directives,
            sources=sources,
            reason="composer_selected_database",
            explicit=True,
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            router_client=router_client,
            router_model=router_model,
            cancellation_token=cancellation_token,
        )
    if request.source_mode == "db_only" or (
        request.source_mode == "auto" and selected is not None
    ):
        return _decision(
            request.source_mode,
            "db_only",
            query_after_directives,
            explicit=True,
            reason="composer_selected_database",
            source=selected,
            sources=selected_sources,
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="database",
            preferred_catalog_id=selected.target_id if selected is not None else None,
            routing_confidence=1.0,
            signal_reason="explicit_database_mode",
        )
    if request.source_mode == "hybrid":
        if selected is None:
            return _routed_database_decision(
                requested_mode=request.source_mode,
                resolved_mode="hybrid",
                semantic_query=query_after_directives,
                sources=sources,
                reason="composer_selected_hybrid",
                explicit=True,
                allow_source_expansion=request.allow_source_expansion,
                structured_score=structured_score,
                corpus_score=corpus_score,
                source_match_score=source_match_score,
                document_match_score=document_match_score,
                router_client=router_client,
                router_model=router_model,
                cancellation_token=cancellation_token,
                preferred_source=preference.preferred_source,
                preference_confidence=preference.confidence,
                preference_reason=preference.reason,
            )
        return _decision(
            request.source_mode,
            "hybrid",
            query_after_directives,
            explicit=True,
            reason="composer_selected_hybrid",
            source=selected,
            sources=selected_sources,
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source=preference.preferred_source,
            preferred_catalog_id=preferred_source_record.target_id if preferred_source_record is not None else None,
            routing_confidence=preference.confidence,
            signal_reason=preference.reason,
        )
    if inline_source is not None:
        return _decision(
            request.source_mode,
            "db_only",
            query_after_directives,
            explicit=True,
            reason="inline_named_connector_source",
            source=inline_source,
            directive="named_source",
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="database",
            preferred_catalog_id=inline_source.target_id,
            routing_confidence=1.0,
            signal_reason="inline_named_database_source",
        )
    if directive == "db":
        return _routed_database_decision(
            requested_mode=request.source_mode,
            resolved_mode="db_only",
            semantic_query=query_after_directives,
            sources=sources,
            reason="inline_database_directive",
            explicit=True,
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            router_client=router_client,
            router_model=router_model,
            cancellation_token=cancellation_token,
            directive=directive,
        )
    if directive == "corpus":
        return _decision(
            request.source_mode,
            "corpus_only",
            query_after_directives,
            explicit=True,
            reason="inline_corpus_directive",
            directive=directive,
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="corpus",
            routing_confidence=1.0,
            signal_reason="inline_corpus_directive",
        )
    if request.document_ids:
        return _decision(
            request.source_mode,
            "corpus_only",
            query_after_directives,
            explicit=True,
            reason="document_scope_selected",
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="corpus",
            routing_confidence=1.0,
            signal_reason="document_scope_selected",
        )
    if not sources:
        return _decision(
            request.source_mode,
            "corpus_only",
            query_after_directives,
            explicit=False,
            reason="no_visible_database_sources",
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="corpus",
            routing_confidence=preference.confidence,
            signal_reason=preference.reason,
        )
    mixed_sources = _requires_mixed_sources(
        query_after_directives,
        source_match_score=source_match_score,
        corpus_score=corpus_score,
        document_match_score=document_match_score,
    )
    resolved_mode: ResolvedSourceMode = (
        "corpus_first"
        if preference.preferred_source == "corpus" and not mixed_sources
        else "hybrid"
    )
    reason = (
        "auto_corpus_first_corpus_preferred"
        if resolved_mode == "corpus_first"
        else "auto_hybrid_all_visible_sources"
    )
    return _decision(
        request.source_mode,
        resolved_mode,
        query_after_directives,
        explicit=False,
        reason=reason,
        allow_source_expansion=request.allow_source_expansion,
        structured_score=structured_score,
        corpus_score=corpus_score,
        source_match_score=source_match_score,
        document_match_score=document_match_score,
        preferred_source=preference.preferred_source,
        preferred_catalog_id=preference.preferred_catalog_id
        or (preferred_source_record.target_id if preferred_source_record is not None else None),
        routing_confidence=preference.confidence,
        router_mode=preference.router_mode,
        signal_reason=preference.reason,
    )


def _planner_source_candidates(
    *,
    source_scores: list[tuple[VisibleQuerySource, int]],
    document_scores: list[tuple[VisibleDocumentSource, int]],
    graph_enabled: bool,
) -> dict[str, object]:
    """Return compact authorized metadata for capability planning."""

    # ponytail: direct cards stay simpler than a second index; add source-card
    # search when a workspace regularly exceeds this bounded candidate set.
    databases = [
        {
            "source_id": source.id,
            "kind": "connector",
            "methods": ["connector_query"],
            "catalog_id": source.target_id,
            "name": source.name[:120],
            "description": (source.description or "")[:500],
            "content_summary": source.match_text[:1000],
            "score": score,
            "routing_profile": {
                key: (
                    [str(item)[:120] for item in value[:3]]
                    if isinstance(value, list)
                    else str(value)[:240]
                )
                for key, value in source.routing_card.items()
            },
        }
        for source, score in sorted(
            source_scores,
            key=lambda item: (item[1], item[0].name.lower()),
            reverse=True,
        )[:12]
    ]
    documents = [
        {
            "source_id": f"document:{document.id}",
            "kind": "indexed_document",
            "methods": ["indexed_search"],
            "document_id": document.id,
            "title": document.title[:200],
            "description": document.match_text[:500],
            "score": score,
        }
        for document, score in sorted(
            document_scores,
            key=lambda item: (item[1], item[0].title.lower()),
            reverse=True,
        )[:5]
    ]
    return {
        "indexes": [
            {
                "source_id": "indexed_corpus",
                "kind": "index",
                "name": "Authorized indexed evidence",
                "description": "Current indexed evidence visible to this user.",
                "methods": ["indexed_search"],
            }
        ],
        "graphs": (
            [
                {
                    "source_id": "knowledge_graph",
                    "kind": "graph",
                    "name": "Authorized knowledge graph",
                    "description": "Relationships derived from authorized indexed evidence.",
                    "methods": ["graph_query"],
                }
            ]
            if graph_enabled
            else []
        ),
        "documents": documents,
        "databases": databases,
    }


def _scope_planner_source_candidates(
    candidates: dict[str, object],
    *,
    requested_mode: str,
    selected_source_ids: tuple[str, ...],
    directive: str | None,
    document_ids: tuple[str, ...],
) -> dict[str, object]:
    """Apply explicit request scope before source metadata reaches the planner."""

    scoped = {
        key: list(value) if isinstance(value, list) else value
        for key, value in candidates.items()
    }
    corpus_only = (
        requested_mode == "corpus_only"
        or directive == "corpus"
        or bool(document_ids)
    )
    database_only = (
        requested_mode == "db_only"
        or directive == "db"
        or (requested_mode == "auto" and bool(selected_source_ids))
    )
    if corpus_only:
        scoped["databases"] = []
    if database_only and not corpus_only:
        for key in ("indexes", "graphs", "documents"):
            scoped[key] = []
    if selected_source_ids:
        selected = set(selected_source_ids)
        scoped["databases"] = [
            item
            for item in scoped.get("databases", [])
            if isinstance(item, dict) and item.get("source_id") in selected
        ]
    if document_ids:
        allowed_document_ids = set(document_ids)
        scoped["documents"] = [
            item
            for item in scoped.get("documents", [])
            if isinstance(item, dict)
            and str(item.get("document_id") or "") in allowed_document_ids
        ]
    return scoped


def selected_source_target(decision: SourceDecision | None) -> tuple[QuerySourceTargetKind, str] | None:
    if decision is None or not decision.query_source_kind or not decision.query_source_record_id:
        return None
    return decision.query_source_kind, decision.query_source_record_id


def selected_source_targets(
    decision: SourceDecision | None,
) -> tuple[tuple[QuerySourceTargetKind, str], ...]:
    if decision is None:
        return ()
    if decision.query_source_record_ids:
        return tuple(("catalog", item) for item in decision.query_source_record_ids)
    selected = selected_source_target(decision)
    return (selected,) if selected is not None else ()


def source_decision_from_evidence_plan(
    decision: SourceDecision,
    evidence_plan: EvidencePlan | None,
    source_candidates: dict[str, object] | None,
) -> SourceDecision:
    """Compile an AI evidence plan into the legacy source execution boundary."""

    if decision.explicit or evidence_plan is None:
        return decision
    database_candidates = {
        str(item.get("source_id")): item
        for item in (source_candidates or {}).get("databases", [])
        if isinstance(item, dict) and item.get("source_id")
    }
    document_candidates = {
        str(item.get("source_id")): item
        for item in (source_candidates or {}).get("documents", [])
        if isinstance(item, dict) and item.get("source_id")
    }
    database_source_ids = tuple(
        dict.fromkeys(
            assignment.source_id
            for need in evidence_plan.needs
            for assignment in need.assignments
            if assignment.capability == "connector_query"
            and assignment.source_id in database_candidates
        )
    )
    document_source_ids = tuple(
        dict.fromkeys(
            assignment.source_id
            for need in evidence_plan.needs
            for assignment in need.assignments
            if assignment.capability == "indexed_search"
            and assignment.source_id in document_candidates
        )
    )
    uses_index = any(
        assignment.capability in {"indexed_search", "graph_query"}
        for need in evidence_plan.needs
        for assignment in need.assignments
    )
    catalog_ids = tuple(
        str(database_candidates[source_id].get("catalog_id") or "")
        for source_id in database_source_ids
        if database_candidates[source_id].get("catalog_id")
    )
    document_ids = tuple(
        str(document_candidates[source_id].get("document_id") or "")
        for source_id in document_source_ids
        if document_candidates[source_id].get("document_id")
    )
    if not catalog_ids:
        return replace(
            decision,
            resolved_mode="corpus_only",
            reason="evidence_plan_selected_indexed_sources",
            query_source_id=None,
            query_source_ids=(),
            query_source_kind=None,
            query_source_record_id=None,
            query_source_record_ids=(),
            preferred_source="corpus",
            preferred_catalog_id=None,
            database_route=None,
            inherited_document_ids=document_ids,
            signal_reason="evidence_plan",
        )
    first_source_id = database_source_ids[0]
    first_catalog_id = catalog_ids[0]
    return replace(
        decision,
        resolved_mode="hybrid" if uses_index else "db_only",
        reason="evidence_plan_selected_sources",
        query_source_id=first_source_id,
        query_source_ids=database_source_ids,
        query_source_kind="catalog",
        query_source_record_id=first_catalog_id,
        query_source_record_ids=catalog_ids,
        preferred_source="balanced" if uses_index else "database",
        preferred_catalog_id=first_catalog_id,
        database_route=None,
        inherited_document_ids=document_ids,
        router_mode="ai_assisted",
        signal_reason="evidence_plan",
    )


def _followup_database_sources(
    turns: list[dict[str, object]],
    antecedent_turn_ids: tuple[str, ...],
    sources: list[VisibleQuerySource],
) -> tuple[tuple[VisibleQuerySource, ...], str | None]:
    visible = {source.id: source for source in sources}
    selected_ids = set(antecedent_turn_ids)
    for index, turn in reversed(tuple(enumerate(turns, start=1))):
        if str(turn.get("turn_id") or f"recent-{index}") not in selected_ids:
            continue
        raw_ids = turn.get("query_source_ids") or (turn.get("query_source_id"),)
        if not isinstance(raw_ids, (list, tuple)):
            raw_ids = (raw_ids,)
        selected = tuple(
            visible[source_id]
            for item in raw_ids
            if (source_id := str(item or "")) in visible
        )
        if selected:
            return selected[:3], str(turn.get("source_mode") or "") or None
    return (), None


def _followup_document_ids(
    turns: list[dict[str, object]],
    antecedent_turn_ids: tuple[str, ...],
    documents: list[VisibleDocumentSource],
) -> tuple[str, ...]:
    visible_ids = {document.id for document in documents}
    selected_ids = set(antecedent_turn_ids)
    inherited: list[str] = []
    for index, turn in enumerate(turns, start=1):
        turn_id = str(turn.get("turn_id") or f"recent-{index}")
        if turn_id not in selected_ids:
            continue
        raw_ids = list(turn.get("document_ids") or [])
        sources = turn.get("sources")
        if isinstance(sources, list):
            raw_ids.extend(
                source.get("doc_id")
                for source in sources
                if isinstance(source, dict)
            )
        for document_id in raw_ids:
            normalized = str(document_id or "").strip()
            if normalized in visible_ids and normalized not in inherited:
                inherited.append(normalized)
    return tuple(inherited[:20])


def _routed_database_decision(
    *,
    requested_mode: str,
    resolved_mode: ResolvedSourceMode,
    semantic_query: str,
    sources: list[VisibleQuerySource],
    reason: str,
    explicit: bool,
    allow_source_expansion: bool,
    structured_score: int,
    corpus_score: int,
    source_match_score: int,
    document_match_score: int,
    router_client: object | None,
    router_model: str | None,
    cancellation_token: object | None,
    directive: str | None = None,
    preferred_source: PreferredSource = "database",
    preference_confidence: float = 0.0,
    preference_reason: str = "",
) -> SourceDecision:
    route = route_database_source(
        semantic_query,
        sources,
        client=router_client,
        model=router_model,
        cancellation_token=cancellation_token,
    )
    selected = next(
        (
            source
            for source in sources
            if source.target_id == route.selected_catalog_id
        ),
        None,
    )
    return _decision(
        requested_mode,
        resolved_mode,
        semantic_query,
        explicit=explicit,
        reason=reason if selected is not None else f"{reason}:database_clarification",
        source=selected,
        directive=directive,
        allow_source_expansion=allow_source_expansion,
        structured_score=structured_score,
        corpus_score=corpus_score,
        source_match_score=source_match_score,
        document_match_score=document_match_score,
        preferred_source=preferred_source,
        preferred_catalog_id=route.selected_catalog_id,
        routing_confidence=(
            1.0
            if selected is not None and route.router_mode == "deterministic"
            else 0.75
            if selected is not None
            else preference_confidence
        ),
        router_mode=route.router_mode,
        signal_reason=preference_reason or route.reason,
        database_route=route,
    )


def _decision(
    requested_mode: str,
    resolved_mode: ResolvedSourceMode,
    semantic_query: str,
    *,
    explicit: bool,
    reason: str,
    source: VisibleQuerySource | None = None,
    sources: tuple[VisibleQuerySource, ...] = (),
    directive: str | None = None,
    allow_source_expansion: bool,
    structured_score: int,
    corpus_score: int,
    source_match_score: int,
    document_match_score: int,
    preferred_source: PreferredSource,
    preferred_catalog_id: str | None = None,
    routing_confidence: float = 0.0,
    router_mode: str = "deterministic",
    signal_reason: str = "",
    database_route: DatabaseRouteDecision | None = None,
    inherited_document_ids: tuple[str, ...] = (),
) -> SourceDecision:
    selected_sources = sources or ((source,) if source is not None else ())
    return SourceDecision(
        requested_mode=requested_mode,
        resolved_mode=resolved_mode,
        semantic_query=semantic_query.strip() or semantic_query,
        explicit=explicit,
        reason=reason,
        directive=directive,
        query_source_id=selected_sources[0].id if selected_sources else None,
        query_source_ids=tuple(item.id for item in selected_sources),
        query_source_kind=selected_sources[0].target_kind if selected_sources else None,
        query_source_record_id=selected_sources[0].target_id if selected_sources else None,
        query_source_record_ids=tuple(item.target_id for item in selected_sources),
        allow_source_expansion=allow_source_expansion,
        structured_score=structured_score,
        corpus_score=corpus_score,
        source_match_score=source_match_score,
        document_match_score=document_match_score,
        preferred_source=preferred_source,
        preferred_catalog_id=preferred_catalog_id,
        routing_confidence=round(max(0.0, min(1.0, routing_confidence)), 3),
        router_mode=router_mode,
        signal_reason=signal_reason,
        database_route=database_route,
        inherited_document_ids=inherited_document_ids,
    )
