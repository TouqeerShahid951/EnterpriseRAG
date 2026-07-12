from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from rag.audit.adapters.memory import RepositoryAuditRepository
from rag.audit.adapters.postgres import PostgresAuditRepository
from rag.audit.models import AuditFilters, AuditViewerScope
from rag.audit.repository import audit_repository_for
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.repositories.document_postgres import PostgresDocumentRepository
from rag.auth.adapters.identity_memory import InMemoryIdentityRepository


class CapturingPostgresAuditRepository(PostgresAuditRepository):
    def __init__(self, *, rows: list[dict[str, Any]]) -> None:
        super().__init__(database_url="postgresql://audit.test/db")
        self.rows = rows
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    def _execute_all(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        self.queries.append((query, params))
        return self.rows


def test_factory_selects_repository_backed_and_postgres_adapters() -> None:
    identity_repo = InMemoryIdentityRepository()

    memory_adapter = audit_repository_for(InMemoryDocumentRepository(), identity_repo)
    postgres_documents = PostgresDocumentRepository("postgresql://documents.test/db")
    postgres_adapter = audit_repository_for(postgres_documents, identity_repo)

    assert isinstance(memory_adapter, RepositoryAuditRepository)
    assert isinstance(postgres_adapter, PostgresAuditRepository)
    assert postgres_adapter.database_url == postgres_documents.database_url


def test_postgres_adapter_builds_scoped_filtered_query_and_enriches_rows() -> None:
    created_from = datetime(2026, 7, 1, tzinfo=UTC)
    created_to = datetime(2026, 7, 10, tzinfo=UTC)
    created_at = datetime(2026, 7, 8, 12, 30, tzinfo=UTC)
    rows = [
        {
            "id": "event-1",
            "event_type": "upload.queued",
            "actor_id": "actor-1",
            "target_type": "document",
            "target_id": "doc-1",
            "payload": json.dumps(
                {"filename": "Payload title.pdf", "group_path": "/finance"}
            ),
            "created_at": created_at,
            "category": "document",
            "actor_email": "actor@example.test",
            "target_user_email": "target@example.test",
            "target_user_name": "Target User",
            "doc_title": "  Quarterly Plan  ",
        },
        {
            "id": "event-2",
            "event_type": "documents.delete",
            "actor_id": None,
            "target_type": "document",
            "target_id": "doc-2",
            "payload": {"filename": "Payload fallback.pdf", "group_path": "/finance"},
            "created_at": created_at,
            "category": "document",
            "actor_email": None,
            "target_user_email": None,
            "target_user_name": None,
            "doc_title": "   ",
        },
    ]
    repository = CapturingPostgresAuditRepository(rows=rows)

    events = repository.search_visible_events(
        filters=AuditFilters(
            search="budget",
            category="document",
            event_type="upload.queued",
            actor_query="alice",
            target_type="document",
            target_id="doc-1",
            group_path="/finance",
            created_from=created_from,
            created_to=created_to,
        ),
        viewer=AuditViewerScope(
            global_access=False,
            group_paths=("/ops", "/finance"),
            clearance_level="NATO_SECRET",
        ),
        scan_limit=9000,
    )

    assert len(repository.queries) == 1
    query, params = repository.queries[0]
    visible_groups = ["/finance", "/ops"]
    assert params[:17] == (
        5000,
        visible_groups,
        ["NATO_UNCLASSIFIED", "NATO_RESTRICTED", "NATO_CONFIDENTIAL", "NATO_SECRET"],
        visible_groups,
        visible_groups,
        "document",
        "upload.queued",
        "alice",
        "alice",
        "document",
        "doc-1",
        "/finance",
        "/finance/",
        "/finance",
        "/finance/",
        created_from,
        created_to,
    )
    assert params[17:] == ("budget",) * 13
    assert "FROM audit_log" in query
    assert "document_shares" in query
    assert "doc_id IS NULL" in query
    assert "payload->>'group_path' = ANY(%s::text[])" in query
    assert "category = %s" in query
    assert "created_at >= %s" in query
    assert "created_at <= %s" in query
    assert "strpos(lower(id), %s) > 0" in query
    assert "budget" not in query

    assert [event.record.id for event in events] == ["event-1", "event-2"]
    assert events[0].record.payload["filename"] == "Payload title.pdf"
    assert events[0].record.created_at == created_at
    assert events[0].actor_email == "actor@example.test"
    assert events[0].target_user_email == "target@example.test"
    assert events[0].target_user_name == "Target User"
    assert events[0].target_document_title == "Quarterly Plan"
    assert events[1].target_document_title == "Payload fallback.pdf"


def test_postgres_adapter_skips_database_for_restricted_viewer_without_groups() -> None:
    repository = CapturingPostgresAuditRepository(rows=[])

    events = repository.search_visible_events(
        filters=_empty_filters(),
        viewer=AuditViewerScope(
            global_access=False,
            group_paths=(),
            clearance_level="NATO_RESTRICTED",
        ),
        scan_limit=100,
    )

    assert events == []
    assert repository.queries == []


def _empty_filters() -> AuditFilters:
    return AuditFilters(
        search="",
        category=None,
        event_type="",
        actor_query="",
        target_type="",
        target_id="",
        group_path="",
        created_from=None,
        created_to=None,
    )
