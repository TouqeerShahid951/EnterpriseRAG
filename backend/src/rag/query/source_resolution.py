"""Query-source decision orchestration and compatibility exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..connectors.repositories import ConnectorProfileRepository
from ..documents.models import DocumentRepository
from ..ingestion.folders.models import FolderScheduleRepository
from .source_advisory import (
    _advisory_llm_source_router as _advisory_llm_source_router,
    _float as _float,
    _source_router_prompt as _source_router_prompt,
    _valid_router_catalog_id as _valid_router_catalog_id,
)
from .source_catalog import (
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
from .source_matching import (
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
    _looks_like_followup as _looks_like_followup,
    _normalize as _normalize,
    _source_match_score as _source_match_score,
    _strip_named_source as _strip_named_source,
    _strip_source_directive as _strip_source_directive,
    _structured_score as _structured_score,
    _term_score as _term_score,
    _tokens as _tokens,
)
from .state import QueryContext, scoped_user_context

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
    query_source_kind: QuerySourceTargetKind | None = None
    query_source_record_id: str | None = None
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


def resolve_query_source(
    ctx: QueryContext,
    *,
    config: object | None = None,
    llm: object | None = None,
    routing_model: str | None = None,
    schedule_repo: FolderScheduleRepository | None = None,
    connector_profile_repo: ConnectorProfileRepository | None = None,
    document_repo: DocumentRepository | None = None,
) -> SourceDecision:
    request = ctx["request"]
    user = scoped_user_context(ctx)
    sources = list_visible_query_sources(
        user,
        schedule_repo=schedule_repo,
        connector_profile_repo=connector_profile_repo,
    )
    documents = list_visible_document_sources(user, document_repo=document_repo)
    selected = validate_query_source_access(
        source_id=request.query_source_id,
        user=user,
        schedule_repo=schedule_repo,
        connector_profile_repo=connector_profile_repo,
    )
    query_after_directives, directive = _strip_source_directive(request.query)
    inline_source = selected if selected is not None else _inline_named_source(query_after_directives, sources)
    if selected is None and inline_source is not None:
        query_after_directives = _strip_named_source(query_after_directives, inline_source)
    structured_score = _structured_score(query_after_directives)
    corpus_score = _term_score(query_after_directives, _CORPUS_TERMS)
    source_scores = [(source, _source_match_score(query_after_directives, source)) for source in sources]
    source_match_score = max((score for _source, score in source_scores), default=0)
    preferred_source_record = _best_scored_source(source_scores)
    document_match_score = max((_document_match_score(query_after_directives, document) for document in documents), default=0)
    db_bias, corpus_bias = _conversation_source_bias(ctx.get("session_turns", []))
    followup = _looks_like_followup(query_after_directives)
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
    if request.source_mode == "db_only" or (request.source_mode == "auto" and selected is not None):
        return _decision(
            request.source_mode,
            "db_only",
            query_after_directives,
            explicit=True,
            reason="composer_selected_database",
            source=selected,
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
        return _decision(
            request.source_mode,
            "hybrid",
            query_after_directives,
            explicit=True,
            reason="composer_selected_hybrid",
            source=selected,
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
        return _decision(
            request.source_mode,
            "db_only",
            query_after_directives,
            explicit=True,
            reason="inline_database_directive",
            directive=directive,
            allow_source_expansion=request.allow_source_expansion,
            structured_score=structured_score,
            corpus_score=corpus_score,
            source_match_score=source_match_score,
            document_match_score=document_match_score,
            preferred_source="database",
            routing_confidence=1.0,
            signal_reason="inline_database_directive",
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
    router = _advisory_llm_source_router(
        query=query_after_directives,
        user=user,
        sources=sources,
        documents=documents,
        session_turns=ctx.get("session_turns", []),
        config=config,
        llm=llm,
        routing_model=routing_model,
        deterministic=preference,
    )
    effective = router or preference
    reason = (
        "auto_hybrid_llm_router"
        if router is not None
        else f"auto_hybrid_{effective.preferred_source}_preferred"
    )
    return _decision(
        request.source_mode,
        "hybrid",
        query_after_directives,
        explicit=False,
        reason=reason,
        allow_source_expansion=request.allow_source_expansion,
        structured_score=structured_score,
        corpus_score=corpus_score,
        source_match_score=source_match_score,
        document_match_score=document_match_score,
        preferred_source=effective.preferred_source,
        preferred_catalog_id=effective.preferred_catalog_id
        or (preferred_source_record.target_id if preferred_source_record is not None else None),
        routing_confidence=effective.confidence,
        router_mode=effective.router_mode,
        signal_reason=effective.reason,
    )


def selected_source_target(decision: SourceDecision | None) -> tuple[QuerySourceTargetKind, str] | None:
    if decision is None or not decision.query_source_kind or not decision.query_source_record_id:
        return None
    return decision.query_source_kind, decision.query_source_record_id


def _decision(
    requested_mode: str,
    resolved_mode: ResolvedSourceMode,
    semantic_query: str,
    *,
    explicit: bool,
    reason: str,
    source: VisibleQuerySource | None = None,
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
) -> SourceDecision:
    return SourceDecision(
        requested_mode=requested_mode,
        resolved_mode=resolved_mode,
        semantic_query=semantic_query.strip() or semantic_query,
        explicit=explicit,
        reason=reason,
        directive=directive,
        query_source_id=source.id if source is not None else None,
        query_source_kind=source.target_kind if source is not None else None,
        query_source_record_id=source.target_id if source is not None else None,
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
    )
