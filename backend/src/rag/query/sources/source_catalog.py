"""Visible query-source discovery, identifiers, and access checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rag.auth.context import UserContext
from rag.connectors.models import ConnectorSchemaCatalogRecord
from rag.connectors.repositories import (
    ConnectorProfileRepository,
    get_connector_profile_repository,
)
from rag.connectors.catalog.schema_catalog import (
    column_allowed,
    schema_catalog_visible_group_path,
    table_allowed,
)
from rag.documents.models import DocumentRecord, DocumentRepository
from rag.ingestion.folders.models import FolderScheduleRepository
from rag.shared.contracts.clearance import can_access_clearance, clearance_rank
from rag.query.schemas import QuerySource

QuerySourceTargetKind = Literal["catalog"]

_SOURCE_PREFIXES = {
    "catalog": "connector_catalog:",
}
_SUPPORTED_SQL_CONNECTOR_TYPES = {"postgres", "sql_server", "fake"}


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
    profile_cache = {
        profile.id: profile for profile in connector_profile_repo.list_profiles()
    }
    for catalog in _current_schema_catalogs(
        connector_profile_repo.list_schema_catalogs()
    ):
        if not _catalog_visible(catalog, user):
            continue
        profile = profile_cache.get(catalog.profile_id)
        profile_name = profile.name if profile is not None else ""
        sources.append(
            _source_from_catalog(catalog, profile_name=profile_name, user=user)
        )
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
        raise QuerySourceAccessError(
            "query_source_forbidden", "Query source is not available to this user."
        )
    return source


def _catalog_visible(catalog: ConnectorSchemaCatalogRecord, user: UserContext) -> bool:
    if catalog.status != "approved":
        return False
    if str(catalog.connector_type) not in _SUPPORTED_SQL_CONNECTOR_TYPES:
        return False
    if (
        schema_catalog_visible_group_path(
            catalog.group_path, catalog.catalog_json, user.group_paths
        )
        is None
    ):
        return False
    return clearance_rank(catalog.clearance_level) <= clearance_rank(
        user.clearance_level
    )


def _document_visible(document: DocumentRecord, user: UserContext) -> bool:
    if not document.is_current:
        return False
    if not can_access_clearance(user.clearance_level, document.clearance_level):
        return False
    visible_groups = set(user.group_paths)
    return bool(visible_groups & set(document.access_group_paths))


def _source_from_catalog(
    catalog: ConnectorSchemaCatalogRecord, *, profile_name: str, user: UserContext
) -> VisibleQuerySource:
    name = _catalog_name(catalog, profile_name=profile_name)
    group_path = (
        schema_catalog_visible_group_path(
            catalog.group_path, catalog.catalog_json, user.group_paths
        )
        or catalog.group_path
    )
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


def _current_schema_catalogs(
    catalogs: list[ConnectorSchemaCatalogRecord],
) -> list[ConnectorSchemaCatalogRecord]:
    by_profile: dict[str, ConnectorSchemaCatalogRecord] = {}
    for catalog in catalogs:
        if catalog.profile_id not in by_profile:
            by_profile[catalog.profile_id] = catalog
    return list(by_profile.values())


def _catalog_name(
    catalog: ConnectorSchemaCatalogRecord, *, profile_name: str
) -> str:
    name = catalog.catalog_json.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return f"{profile_name or catalog.connector_type} approved database scope"


def _catalog_match_text(catalog_json: dict[str, object]) -> str:
    parts: list[str] = []
    for table in catalog_json.get("tables") or []:
        if not isinstance(table, dict) or not table_allowed(table):
            continue
        parts.extend(
            str(table.get(field) or "")
            for field in ("key", "schema", "name", "description")
        )
        parts.extend(str(item) for item in table.get("synonyms") or [])
        for column in table.get("columns") or []:
            if not isinstance(column, dict) or not column_allowed(column):
                continue
            parts.extend(
                str(column.get(field) or "")
                for field in ("name", "data_type", "description")
            )
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


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
