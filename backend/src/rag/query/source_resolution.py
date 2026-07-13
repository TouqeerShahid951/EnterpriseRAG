"""Query source discovery and routing decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass
import re
from typing import Literal

from ..auth.context import UserContext
from ..connectors.models import ConnectorSchemaCatalogRecord
from ..connectors.repositories import ConnectorProfileRepository, get_connector_profile_repository
from ..connectors.schema_catalog import column_allowed, schema_catalog_visible_group_path, table_allowed
from ..documents.models import DocumentRecord, DocumentRepository
from ..ingestion.folders.models import FolderScheduleRepository
from .schemas import QuerySource
from ..shared.contracts.clearance import can_access_clearance, clearance_rank
from .state import QueryContext, scoped_user_context

QuerySourceTargetKind = Literal["catalog"]
ResolvedSourceMode = Literal["corpus_only", "db_only", "db_first", "corpus_first", "hybrid"]
PreferredSource = Literal["database", "corpus", "balanced"]

_SOURCE_PREFIXES = {
    "catalog": "connector_catalog:",
}
_SUPPORTED_SQL_CONNECTOR_TYPES = {"postgres", "sql_server", "fake"}
_DB_DIRECTIVE_RE = re.compile(
    r"\b(?:in|from|using|use|query|search)\s+(?:the\s+)?(?:live\s+)?(?:db|database)\b",
    flags=re.IGNORECASE,
)
_CORPUS_DIRECTIVE_RE = re.compile(
    r"\b(?:in|from|using|use|search)\s+(?:the\s+)?(?:docs?|documents?|corpus|knowledge\s+space|uploaded\s+docs?)\b",
    flags=re.IGNORECASE,
)
_STRUCTURED_TERMS = {
    "average",
    "count",
    "counts",
    "current",
    "filter",
    "group",
    "latest",
    "list",
    "maximum",
    "minimum",
    "oldest",
    "records",
    "rows",
    "show",
    "sort",
    "sum",
    "total",
    "totals",
}
_CORPUS_TERMS = {
    "according",
    "clause",
    "contract",
    "define",
    "describe",
    "document",
    "documents",
    "explain",
    "manual",
    "page",
    "policy",
    "procedure",
    "summarize",
    "summary",
}


@dataclass(frozen=True)
class VisibleQuerySource:
    id: str
    target_kind: QuerySourceTargetKind
    target_id: str
    name: str
    description: str | None
    connector_type: str
    scope: Literal["database_scope"]
    group_path: str
    clearance_level: str
    match_text: str


@dataclass(frozen=True)
class VisibleDocumentSource:
    id: str
    title: str
    group_path: str
    clearance_level: str
    match_text: str


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


@dataclass(frozen=True)
class _SourcePreference:
    preferred_source: PreferredSource
    confidence: float
    reason: str
    preferred_catalog_id: str | None = None
    router_mode: str = "deterministic"


class QuerySourceAccessError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def query_source_id_for_catalog(catalog_id: str) -> str:
    return f"{_SOURCE_PREFIXES['catalog']}{catalog_id}"


def parse_query_source_id(source_id: str | None) -> tuple[QuerySourceTargetKind, str] | None:
    if not source_id:
        return None
    for kind, prefix in _SOURCE_PREFIXES.items():
        if source_id.startswith(prefix):
            record_id = source_id.removeprefix(prefix).strip()
            if record_id:
                return kind, record_id  # type: ignore[return-value]
    raise QuerySourceAccessError("invalid_query_source", "Query source identifier is invalid.")


def list_visible_query_sources(
    user: UserContext,
    *,
    schedule_repo: FolderScheduleRepository | None = None,
    connector_profile_repo: ConnectorProfileRepository | None = None,
) -> list[VisibleQuerySource]:
    _ = schedule_repo
    connector_profile_repo = connector_profile_repo or get_connector_profile_repository()
    sources: list[VisibleQuerySource] = []
    profile_cache = {profile.id: profile for profile in connector_profile_repo.list_profiles()}
    for catalog in _current_schema_catalogs(connector_profile_repo.list_schema_catalogs()):
        if not _catalog_visible(catalog, user):
            continue
        profile = profile_cache.get(catalog.profile_id)
        profile_name = profile.name if profile is not None else ""
        sources.append(_source_from_catalog(catalog, profile_name=profile_name, user=user))
    return sorted(sources, key=lambda item: (item.scope, item.name.lower(), item.id))


def list_visible_document_sources(
    user: UserContext,
    *,
    document_repo: DocumentRepository | None = None,
) -> list[VisibleDocumentSource]:
    if document_repo is None:
        return []
    documents: list[VisibleDocumentSource] = []
    for document in document_repo.list_documents(state="active"):
        if not _document_visible(document, user):
            continue
        documents.append(
            VisibleDocumentSource(
                id=document.id,
                title=document.title or document.source_id,
                group_path=document.group_path,
                clearance_level=document.clearance_level,
                match_text=_document_match_text(document),
            )
        )
    return documents


def public_query_source(source: VisibleQuerySource) -> QuerySource:
    return QuerySource(
        id=source.id,
        kind="connector_schema_catalog",
        name=source.name,
        description=source.description,
        connector_type=source.connector_type,
        scope=source.scope,
        group_path=source.group_path,
        clearance_level=source.clearance_level,  # type: ignore[arg-type]
    )


def validate_query_source_access(
    *,
    source_id: str | None,
    user: UserContext,
    schedule_repo: FolderScheduleRepository | None = None,
    connector_profile_repo: ConnectorProfileRepository | None = None,
) -> VisibleQuerySource | None:
    parsed = parse_query_source_id(source_id)
    if parsed is None:
        return None
    visible = {
        (source.target_kind, source.target_id): source
        for source in list_visible_query_sources(
            user,
            schedule_repo=schedule_repo,
            connector_profile_repo=connector_profile_repo,
        )
    }
    source = visible.get(parsed)
    if source is None:
        raise QuerySourceAccessError("query_source_forbidden", "Query source is not available to this user.")
    return source


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


def _catalog_visible(catalog: ConnectorSchemaCatalogRecord, user: UserContext) -> bool:
    if catalog.status != "approved":
        return False
    if str(catalog.connector_type) not in _SUPPORTED_SQL_CONNECTOR_TYPES:
        return False
    if schema_catalog_visible_group_path(catalog.group_path, catalog.catalog_json, user.group_paths) is None:
        return False
    return clearance_rank(catalog.clearance_level) <= clearance_rank(user.clearance_level)


def _document_visible(document: DocumentRecord, user: UserContext) -> bool:
    if not document.is_current:
        return False
    if not can_access_clearance(user.clearance_level, document.clearance_level):
        return False
    visible_groups = set(user.group_paths)
    return bool(visible_groups & set(document.access_group_paths))


def _source_from_catalog(catalog: ConnectorSchemaCatalogRecord, *, profile_name: str, user: UserContext) -> VisibleQuerySource:
    name = _catalog_name(catalog, profile_name=profile_name)
    group_path = schema_catalog_visible_group_path(catalog.group_path, catalog.catalog_json, user.group_paths) or catalog.group_path
    match_text = " ".join(
        item
        for item in (
            name,
            profile_name,
            _catalog_match_text(catalog.catalog_json),
        )
        if item
    )
    return VisibleQuerySource(
        id=query_source_id_for_catalog(catalog.id),
        target_kind="catalog",
        target_id=catalog.id,
        name=name,
        description=_optional_str(catalog.catalog_json.get("description")),
        connector_type=str(catalog.connector_type),
        scope="database_scope",
        group_path=group_path,
        clearance_level=catalog.clearance_level,
        match_text=match_text,
    )


def _current_schema_catalogs(catalogs: list[ConnectorSchemaCatalogRecord]) -> list[ConnectorSchemaCatalogRecord]:
    by_profile: dict[str, ConnectorSchemaCatalogRecord] = {}
    for catalog in catalogs:
        if catalog.profile_id not in by_profile:
            by_profile[catalog.profile_id] = catalog
    return list(by_profile.values())


def _catalog_name(catalog: ConnectorSchemaCatalogRecord, *, profile_name: str) -> str:
    name = catalog.catalog_json.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return f"{profile_name or catalog.connector_type} approved database scope"


def _catalog_match_text(catalog_json: dict[str, object]) -> str:
    parts: list[str] = []
    for table in catalog_json.get("tables") or []:
        if not isinstance(table, dict) or not table_allowed(table):
            continue
        parts.extend(str(table.get(field) or "") for field in ("key", "schema", "name", "description"))
        parts.extend(str(item) for item in table.get("synonyms") or [])
        for column in table.get("columns") or []:
            if not isinstance(column, dict) or not column_allowed(column):
                continue
            parts.extend(str(column.get(field) or "") for field in ("name", "data_type", "description"))
            parts.extend(str(item) for item in column.get("synonyms") or [])
    return " ".join(part for part in parts if part)


def _document_match_text(document: DocumentRecord) -> str:
    parts: list[str] = [
        document.title or "",
        document.source_id,
        document.doc_type or "",
        document.auto_doc_type or "",
        document.description or "",
        document.summary or "",
        document.language or "",
    ]
    parts.extend(document.topics)
    parts.extend(document.llm_topics)
    if document.effective_date is not None:
        parts.append(document.effective_date.isoformat())
    if document.expiry_date is not None:
        parts.append(document.expiry_date.isoformat())
    for value in document.extracted_dates.values():
        parts.append(str(value))
    return " ".join(part for part in parts if part)


def _strip_source_directive(query: str) -> tuple[str, str | None]:
    if _DB_DIRECTIVE_RE.search(query):
        return _compact_query(_DB_DIRECTIVE_RE.sub(" ", query)), "db"
    if _CORPUS_DIRECTIVE_RE.search(query):
        return _compact_query(_CORPUS_DIRECTIVE_RE.sub(" ", query)), "corpus"
    return query.strip(), None


def _inline_named_source(query: str, sources: list[VisibleQuerySource]) -> VisibleQuerySource | None:
    normalized = _normalize(query)
    for source in sources:
        name = _normalize(source.name)
        if len(name) < 4:
            continue
        if f"use {name}" in normalized or f"using {name}" in normalized or f"from {name}" in normalized:
            return source
    return None


def _strip_named_source(query: str, source: VisibleQuerySource) -> str:
    name = re.escape(source.name)
    stripped = re.sub(rf"\b(?:use|using|from)\s+{name}\b", " ", query, flags=re.IGNORECASE)
    return _compact_query(stripped)


def _term_score(query: str, terms: set[str]) -> int:
    tokens = set(_tokens(query))
    return len(tokens & terms)


def _structured_score(query: str) -> int:
    tokens = set(_tokens(query))
    score = _term_score(query, _STRUCTURED_TERMS)
    lowered = f" {query.lower()} "
    if " by " in lowered and {"count", "sum", "total", "average"} & tokens:
        score += 1
    if re.search(r"\btop\s+\d+\b", query, flags=re.IGNORECASE):
        score += 1
    return score


def _source_match_score(query: str, source: VisibleQuerySource) -> int:
    query_tokens = set(_tokens(query))
    source_tokens = set(_tokens(source.match_text))
    return len(query_tokens & source_tokens)


def _document_match_score(query: str, document: VisibleDocumentSource) -> int:
    query_tokens = set(_tokens(query))
    document_tokens = set(_tokens(document.match_text))
    return len(query_tokens & document_tokens)


def _best_scored_source(scored: list[tuple[VisibleQuerySource, int]]) -> VisibleQuerySource | None:
    if not scored:
        return None
    source, score = max(scored, key=lambda item: item[1])
    return source if score > 0 else None


def _deterministic_preference(
    *,
    structured_score: int,
    corpus_score: int,
    source_match_score: int,
    document_match_score: int,
    db_bias: int,
    corpus_bias: int,
) -> _SourcePreference:
    db_score = source_match_score + (structured_score * 2) + db_bias
    doc_score = document_match_score + (corpus_score * 2) + corpus_bias
    margin = db_score - doc_score
    if margin >= 2:
        preferred: PreferredSource = "database"
    elif margin <= -2:
        preferred = "corpus"
    else:
        preferred = "balanced"
    total = max(1, db_score + doc_score)
    confidence = 0.5 + min(0.45, abs(margin) / max(4, total))
    reason = f"db_score={db_score},doc_score={doc_score},margin={margin}"
    return _SourcePreference(preferred, confidence, reason)


def _conversation_source_bias(turns: list[dict[str, object]]) -> tuple[int, int]:
    db_bias = 0
    corpus_bias = 0
    for turn in turns[-3:]:
        mode = str(turn.get("source_mode") or "")
        preferred = str(turn.get("preferred_source") or "")
        if mode in {"db_only", "db_first"} or preferred == "database":
            db_bias += 2
        elif mode == "corpus_only" or preferred == "corpus":
            corpus_bias += 2
        elif mode == "hybrid" or preferred == "balanced":
            db_bias += 1
            corpus_bias += 1
        for source in turn.get("sources") or []:
            if not isinstance(source, dict):
                continue
            doc_id = str(source.get("doc_id") or "")
            if doc_id.startswith("connector-live-scope:"):
                db_bias += 1
            elif doc_id:
                corpus_bias += 1
    return db_bias, corpus_bias


def _looks_like_followup(query: str) -> bool:
    normalized = _normalize(query)
    tokens = normalized.split()
    if len(tokens) <= 4 and tokens:
        return True
    return any(
        phrase in f" {normalized} "
        for phrase in (
            " what about ",
            " and ",
            " those ",
            " them ",
            " it ",
            " same ",
            " also ",
        )
    )


def _advisory_llm_source_router(
    *,
    query: str,
    user: UserContext,
    sources: list[VisibleQuerySource],
    documents: list[VisibleDocumentSource],
    session_turns: list[dict[str, object]],
    config: object | None,
    llm: object | None,
    routing_model: str | None,
    deterministic: _SourcePreference,
) -> _SourcePreference | None:
    if not bool(getattr(config, "rag_source_router_llm_enabled", False)):
        return None
    if llm is None or not sources or not documents:
        return None
    if deterministic.preferred_source != "balanced" and deterministic.confidence >= 0.70:
        return None
    generator = getattr(llm, "generate_json", None)
    if generator is None:
        return None
    try:
        raw = generator(
            prompt=_source_router_prompt(
                query=query,
                user=user,
                sources=sources,
                documents=documents,
                session_turns=session_turns,
                deterministic=deterministic,
            ),
            model=routing_model,
            system="You choose source priority for a retrieval system without excluding available sources.",
            max_tokens=512,
        )
        payload = json.loads(str(raw))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    confidence = _float(payload.get("confidence"))
    threshold = float(getattr(config, "rag_source_router_llm_min_confidence", 0.60) or 0.60)
    if confidence < threshold:
        return None
    preferred = str(payload.get("preferred_source") or "").strip().lower()
    if preferred not in {"database", "corpus", "balanced"}:
        return None
    catalog_id = _valid_router_catalog_id(payload.get("preferred_catalog_id"), sources)
    reason = _compact_query(str(payload.get("reason") or "llm_source_router"))[:240]
    return _SourcePreference(
        preferred,  # type: ignore[arg-type]
        confidence,
        reason,
        preferred_catalog_id=catalog_id,
        router_mode="llm",
    )


def _source_router_prompt(
    *,
    query: str,
    user: UserContext,
    sources: list[VisibleQuerySource],
    documents: list[VisibleDocumentSource],
    session_turns: list[dict[str, object]],
    deterministic: _SourcePreference,
) -> str:
    payload = {
        "query": query,
        "workspace_group_paths": list(user.group_paths),
        "deterministic_preference": {
            "preferred_source": deterministic.preferred_source,
            "confidence": deterministic.confidence,
            "reason": deterministic.reason,
        },
        "visible_database_catalogs": [
            {
                "id": source.target_id,
                "name": source.name,
                "description": source.description,
                "connector_type": source.connector_type,
                "summary": _compact_query(source.match_text)[:900],
            }
            for source in sources[:6]
        ],
        "visible_documents": [
            {
                "id": document.id,
                "title": document.title,
                "summary": _compact_query(document.match_text)[:700],
            }
            for document in documents[:8]
        ],
        "recent_turns": [
            {
                "query": str(turn.get("query") or "")[:240],
                "answer": str(turn.get("answer") or "")[:300],
                "source_mode": turn.get("source_mode"),
                "preferred_source": turn.get("preferred_source"),
            }
            for turn in session_turns[-3:]
        ],
    }
    return (
        "Choose which source should be prioritized for this Auto query. "
        "Do not exclude sources; Auto will still search both database and documents. "
        "Return only JSON with keys preferred_source, preferred_catalog_id, confidence, and reason. "
        'preferred_source must be one of "database", "corpus", or "balanced". '
        "preferred_catalog_id must be one of the visible database catalog ids or null.\n\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)}"
    )


def _valid_router_catalog_id(value: object, sources: list[VisibleQuerySource]) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    valid_ids = {source.target_id for source in sources}
    valid_source_ids = {source.id: source.target_id for source in sources}
    if candidate in valid_ids:
        return candidate
    return valid_source_ids.get(candidate)


def _float(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _tokens(value: str) -> list[str]:
    return [match.group(0).lower() for match in re.finditer(r"[A-Za-z0-9_]{3,}", value)]


def _normalize(value: str) -> str:
    return " ".join(_tokens(value))


def _compact_query(value: str) -> str:
    return " ".join(value.split()).strip()


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
