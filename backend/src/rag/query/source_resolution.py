"""Query source discovery and routing decisions."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from ..auth.context import UserContext
from ..connectors.models import ConnectorSchemaCatalogRecord
from ..connectors.repositories import ConnectorProfileRepository, get_connector_profile_repository
from ..connectors.schema_catalog import column_allowed, schema_catalog_visible_group_path, table_allowed
from ..repositories.folder_schedule_models import FolderScheduleRepository
from ..schemas.query import QuerySource
from ..shared.contracts.clearance import clearance_rank
from .state import QueryContext, scoped_user_context

QuerySourceTargetKind = Literal["catalog"]
ResolvedSourceMode = Literal["corpus_only", "db_only", "db_first", "corpus_first", "hybrid"]

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
    schedule_repo: FolderScheduleRepository | None = None,
    connector_profile_repo: ConnectorProfileRepository | None = None,
) -> SourceDecision:
    request = ctx["request"]
    user = scoped_user_context(ctx)
    sources = list_visible_query_sources(
        user,
        schedule_repo=schedule_repo,
        connector_profile_repo=connector_profile_repo,
    )
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
    source_match_score = max((_source_match_score(query_after_directives, source) for source in sources), default=0)
    explicit = request.source_mode != "auto" or bool(request.query_source_id)

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
        )
    if structured_score > 0 and corpus_score > 0 and source_match_score > 0:
        resolved: ResolvedSourceMode = "hybrid"
        reason = "mixed_structured_and_corpus_signals"
    elif structured_score > 0 and source_match_score > 0:
        resolved = "db_first"
        reason = "structured_query_matches_database_scope"
    elif corpus_score > 0:
        resolved = "corpus_only"
        reason = "corpus_language_detected"
    else:
        resolved = "corpus_first"
        reason = "auto_default_corpus_first"
    return _decision(
        request.source_mode,
        resolved,
        query_after_directives,
        explicit=False,
        reason=reason,
        allow_source_expansion=request.allow_source_expansion,
        structured_score=structured_score,
        corpus_score=corpus_score,
        source_match_score=source_match_score,
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
    )


def _catalog_visible(catalog: ConnectorSchemaCatalogRecord, user: UserContext) -> bool:
    if catalog.status != "approved":
        return False
    if str(catalog.connector_type) not in _SUPPORTED_SQL_CONNECTOR_TYPES:
        return False
    if schema_catalog_visible_group_path(catalog.group_path, catalog.catalog_json, user.group_paths) is None:
        return False
    return clearance_rank(catalog.clearance_level) <= clearance_rank(user.clearance_level)


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


def _tokens(value: str) -> list[str]:
    return [match.group(0).lower() for match in re.finditer(r"[A-Za-z0-9_]{3,}", value)]


def _normalize(value: str) -> str:
    return " ".join(_tokens(value))


def _compact_query(value: str) -> str:
    return " ".join(value.split()).strip()


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
