from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from rag.auth.context import UserContext
from rag.connectors.models import ConnectorSchemaCatalogRecord
from rag.connectors.repositories import InMemoryConnectorProfileRepository
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.query.source_resolution import (
    QuerySourceAccessError,
    list_visible_query_sources,
    public_query_source,
    query_source_id_for_catalog,
    resolve_query_source,
    selected_source_target,
    validate_query_source_access,
)
from rag.query.source_routes import list_query_sources
from rag.query.state import initial_state
from rag.ingestion.folders.adapters.memory import InMemoryFolderScheduleRepository
from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.query.schemas import QueryRequest


def test_query_request_rejects_contradictory_source_scopes() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(query="Summarize policy", source_mode="corpus_only", query_source_id="connector_catalog:cat-1")

    with pytest.raises(ValidationError):
        QueryRequest(query="Count cases", source_mode="db_only", document_ids=["doc-1"])


def test_visible_query_sources_only_return_approved_accessible_scopes() -> None:
    schedule_repo, profile_repo, approved_catalog = _repos_with_sources()
    reviewed_profile = _add_profile(profile_repo, profile_id="profile-reviewed", name="Reviewed warehouse")
    finance_profile = _add_profile(profile_repo, profile_id="profile-finance", name="Finance warehouse")
    secret_profile = _add_profile(profile_repo, profile_id="profile-secret", name="Secret warehouse")
    _add_catalog(profile_repo, profile_id=reviewed_profile.id, status="reviewed", group_path="/ops", name="Reviewed scope")
    _add_catalog(profile_repo, profile_id=finance_profile.id, status="approved", group_path="/finance", name="Finance scope")
    _add_catalog(profile_repo, profile_id=secret_profile.id, status="approved", group_path="/ops", clearance_level="NATO_SECRET", name="Secret scope")
    _add_schedule(schedule_repo, profile_id=_profile_id(profile_repo), status="paused", name="Paused schedule")
    _add_schedule(
        schedule_repo,
        profile_id=_profile_id(profile_repo),
        status="active",
        name="Expired schedule",
        expiry_date=date.today() - timedelta(days=1),
    )

    sources = list_visible_query_sources(
        _user(),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )
    public_sources = [public_query_source(source) for source in sources]

    assert {source.id for source in sources} == {
        query_source_id_for_catalog(approved_catalog.id),
    }
    assert {source.kind for source in public_sources} == {"connector_schema_catalog"}
    assert all(source.group_path == "/ops" for source in public_sources)
    assert all("secret" not in source.model_dump() for source in public_sources)


def test_visible_query_sources_include_catalogs_shared_to_user_space() -> None:
    schedule_repo, profile_repo, approved_catalog = _repos_with_sources()
    profile_repo.update_schema_catalog(
        approved_catalog.id,
        catalog_json={**approved_catalog.catalog_json, "shared_group_paths": ["/finance"]},
    )

    sources = list_visible_query_sources(
        _user(group_paths=("/finance",)),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert {source.id for source in sources} == {query_source_id_for_catalog(approved_catalog.id)}
    assert sources[0].group_path == "/finance"


def test_query_sources_route_returns_public_visible_sources() -> None:
    schedule_repo, profile_repo, approved_catalog = _repos_with_sources()
    identity_repo = InMemoryIdentityRepository()
    identity_repo.create_group(path="/ops", name="Ops")
    user = identity_repo.create_user(
        email="user@example.test",
        name="User",
        password_hash="hash",
        group_paths=["/ops"],
        is_active=True,
        account_type="member",
        clearance_level="NATO_RESTRICTED",
    )

    response = asyncio.run(
        list_query_sources(
            group_path="/ops",
            user=user,
            identity_repo=identity_repo,
            schedule_repo=schedule_repo,
            connector_profile_repo=profile_repo,
        )
    )

    assert response.total == 1
    assert {item.id for item in response.items} == {
        query_source_id_for_catalog(approved_catalog.id),
    }
    assert all(item.connector_type == "fake" for item in response.items)
    assert all(item.group_path == "/ops" for item in response.items)


def test_validate_query_source_access_rejects_invalid_or_hidden_ids() -> None:
    schedule_repo, profile_repo, _approved = _repos_with_sources()
    finance_profile = _add_profile(profile_repo, profile_id="profile-finance", name="Finance warehouse")
    hidden = _add_catalog(profile_repo, profile_id=finance_profile.id, status="approved", group_path="/finance", name="Finance scope")

    with pytest.raises(QuerySourceAccessError) as invalid:
        validate_query_source_access(source_id="profile:raw", user=_user(), schedule_repo=schedule_repo, connector_profile_repo=profile_repo)
    assert invalid.value.code == "invalid_query_source"

    with pytest.raises(QuerySourceAccessError) as retired:
        validate_query_source_access(source_id="connector_schedule:case-schedule", user=_user(), schedule_repo=schedule_repo, connector_profile_repo=profile_repo)
    assert retired.value.code == "invalid_query_source"

    with pytest.raises(QuerySourceAccessError) as forbidden:
        validate_query_source_access(
            source_id=query_source_id_for_catalog(hidden.id),
            user=_user(),
            schedule_repo=schedule_repo,
            connector_profile_repo=profile_repo,
        )
    assert forbidden.value.code == "query_source_forbidden"


def test_source_resolver_composer_mode_overrides_inline_hint() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    decision = resolve_query_source(
        _ctx(QueryRequest(query="Count cases in DB", source_mode="corpus_only")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "corpus_only"
    assert decision.reason == "composer_selected_corpus"
    assert decision.semantic_query == "Count cases"
    assert decision.directive is None


def test_source_resolver_inline_hints_strip_directives() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()

    db_decision = resolve_query_source(
        _ctx(QueryRequest(query="List open cases from database")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )
    doc_decision = resolve_query_source(
        _ctx(QueryRequest(query="Explain the policy from documents")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert db_decision.resolved_mode == "db_only"
    assert db_decision.reason == "inline_database_directive"
    assert db_decision.semantic_query == "List open cases"
    assert doc_decision.resolved_mode == "corpus_only"
    assert doc_decision.reason == "inline_corpus_directive"
    assert doc_decision.semantic_query == "Explain the policy"


def test_source_resolver_auto_routes_structured_schema_matches_to_db_first() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="Count cases by status")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.reason == "auto_hybrid_database_preferred"
    assert decision.preferred_source == "database"
    assert decision.structured_score > 0
    assert decision.source_match_score > 0


def test_source_resolver_auto_routes_schema_term_matches_to_db_first() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="What is the status of case CASE-2025-5002?")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.reason == "auto_hybrid_database_preferred"
    assert decision.preferred_source == "database"
    assert decision.structured_score == 0
    assert decision.source_match_score >= 2


def test_source_resolver_auto_keeps_policy_questions_in_corpus() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="Explain the retention policy")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.reason == "auto_hybrid_corpus_preferred"
    assert decision.preferred_source == "corpus"
    assert decision.corpus_score > 0


def test_source_resolver_auto_routes_mixed_database_and_corpus_signals_to_hybrid() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="Count cases by status according to the policy")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.reason.startswith("auto_hybrid_")
    assert decision.structured_score > 0
    assert decision.corpus_score > 0
    assert decision.source_match_score > 0


def test_source_resolver_auto_without_visible_database_stays_corpus_only() -> None:
    schedule_repo = InMemoryFolderScheduleRepository()
    profile_repo = InMemoryConnectorProfileRepository()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="What is the current status?")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "corpus_only"
    assert decision.reason == "no_visible_database_sources"
    assert decision.preferred_source == "corpus"


def test_source_resolver_auto_uses_document_metadata_for_corpus_preference() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    document_repo = _document_repo_with_policy()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="What does the retention manual say?")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=document_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.preferred_source == "corpus"
    assert decision.document_match_score > 0


def test_source_resolver_auto_followup_inherits_previous_source_bias() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    ctx = _ctx(QueryRequest(query="What about pending ones?"))
    ctx["session_turns"] = [
        {
            "query": "Which cases are open?",
            "answer": "Open cases...",
            "source_mode": "hybrid",
            "preferred_source": "database",
            "sources": [{"doc_id": "connector-live-scope:catalog"}],
        }
    ]

    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.preferred_source == "database"
    assert "db_score" in decision.signal_reason


def test_source_resolver_auto_llm_router_is_advisory_when_ambiguous() -> None:
    schedule_repo, profile_repo, catalog = _repos_with_sources()
    document_repo = _document_repo_with_policy()
    llm = FakeRouterLlm(
        {
            "preferred_source": "corpus",
            "preferred_catalog_id": catalog.id,
            "confidence": 0.92,
            "reason": "manual title matches",
        }
    )

    decision = resolve_query_source(
        _ctx(QueryRequest(query="case retention")),
        config=FakeSourceRouterConfig(),
        llm=llm,
        routing_model="router",
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=document_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.router_mode == "llm"
    assert decision.preferred_source == "corpus"
    assert decision.preferred_catalog_id == catalog.id
    assert llm.calls == 1


def test_source_resolver_auto_ignores_low_confidence_llm_router() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    document_repo = _document_repo_with_policy()
    llm = FakeRouterLlm({"preferred_source": "corpus", "confidence": 0.2, "reason": "weak"})

    decision = resolve_query_source(
        _ctx(QueryRequest(query="case retention")),
        config=FakeSourceRouterConfig(),
        llm=llm,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=document_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.router_mode == "deterministic"
    assert llm.calls == 1


def test_source_resolver_selected_source_sets_opaque_target() -> None:
    schedule_repo, profile_repo, catalog = _repos_with_sources()
    source_id = query_source_id_for_catalog(catalog.id)

    decision = resolve_query_source(
        _ctx(QueryRequest(query="List open cases from documents", source_mode="db_only", query_source_id=source_id)),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "db_only"
    assert decision.reason == "composer_selected_database"
    assert decision.semantic_query == "List open cases"
    assert selected_source_target(decision) == ("catalog", catalog.id)


def _repos_with_sources() -> tuple[InMemoryFolderScheduleRepository, InMemoryConnectorProfileRepository, ConnectorSchemaCatalogRecord]:
    schedule_repo = InMemoryFolderScheduleRepository()
    profile_repo = InMemoryConnectorProfileRepository()
    profile = profile_repo.create_profile(
        profile_id="profile-1",
        name="Case warehouse",
        connector_type="fake",
        public_config={},
        encrypted_secrets="encrypted",
        created_by="admin",
    )
    catalog = _add_catalog(profile_repo, profile_id=profile.id)
    _add_schedule(schedule_repo, profile_id=profile.id)
    return schedule_repo, profile_repo, catalog


def _add_profile(profile_repo: InMemoryConnectorProfileRepository, *, profile_id: str, name: str):
    return profile_repo.create_profile(
        profile_id=profile_id,
        name=name,
        connector_type="fake",
        public_config={},
        encrypted_secrets="encrypted",
        created_by="admin",
    )


def _add_catalog(
    profile_repo: InMemoryConnectorProfileRepository,
    *,
    profile_id: str = "profile-1",
    status: str = "approved",
    group_path: str = "/ops",
    clearance_level: str = "NATO_RESTRICTED",
    name: str = "Cases approved database scope",
) -> ConnectorSchemaCatalogRecord:
    return profile_repo.save_schema_catalog(
        profile_id=profile_id,
        connector_type="fake",
        status=status,
        group_path=group_path,
        clearance_level=clearance_level,
        created_by="admin",
        approved_by="admin" if status == "approved" else None,
        catalog_json={
            "version": 1,
            "name": name,
            "description": "Approved case and incident database tables.",
            "tables": [
                {
                    "key": "fake.cases",
                    "schema": "fake",
                    "name": "cases",
                    "description": "Operational case records.",
                    "allowed": True,
                    "sensitive": False,
                    "synonyms": ["incidents"],
                    "columns": [
                        {"name": "id", "data_type": "text", "allowed": True, "sensitive": False},
                        {"name": "status", "data_type": "text", "allowed": True, "sensitive": False},
                    ],
                }
            ],
            "relationships": [],
        },
    )


def _add_schedule(
    schedule_repo: InMemoryFolderScheduleRepository,
    *,
    profile_id: str,
    status: str = "active",
    name: str = "Case schedule",
    expiry_date: date | None = None,
) -> None:
    schedule_repo.create_schedule(
        schedule_id="case-schedule" if name == "Case schedule" else None,
        name=name,
        source_type="connector",
        schedule_type="recurring",
        status=status,
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="case record",
        effective_date=None,
        expiry_date=expiry_date,
        description="Approved case schedule",
        timezone="Asia/Karachi",
        scheduled_at=None,
        recurrence={},
        source_config={
            "connector_profile_id": profile_id,
            "connector_type": "fake",
            "selection": {"query": "SELECT id, status FROM fake.cases"},
            "identity_fields": ["id"],
            "row_limit": 100,
        },
        created_by="admin",
        next_run_at=datetime.now(UTC),
    )


def _document_repo_with_policy() -> InMemoryDocumentRepository:
    repo = InMemoryDocumentRepository()
    document = repo.create_document(
        document_id="doc-policy",
        title="Retention manual",
        source_id="retention-manual.pdf",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="manual",
        effective_date=None,
        expiry_date=None,
        description="Document retention policy and procedures",
        pending_supersedes=[],
        content_hash="hash-policy",
        uploaded_by="user",
        file_path="/tmp/retention-manual.pdf",
        ingest_status="completed",
    )
    repo.save_document_metadata(
        document_id=document.id,
        summary="Retention manual for document policy questions.",
        language="en",
        topics=["retention", "policy"],
        llm_topics=["manual"],
        doc_type="manual",
        auto_doc_type="policy",
        extracted_dates={},
        metadata_flags={},
        entities=[],
        cross_references=[],
    )
    return repo


def _ctx(request: QueryRequest):
    return initial_state(
        trace_id="trace",
        session_id="session",
        request=request,
        user=_user(),
        started=0.0,
    )


def _user(*, group_paths: tuple[str, ...] = ("/ops",)) -> UserContext:
    return UserContext(
        user_id="user",
        email="user@example.test",
        group_paths=group_paths,
        clearance_level="NATO_RESTRICTED",
    )


def _profile_id(profile_repo: InMemoryConnectorProfileRepository) -> str:
    return profile_repo.list_profiles()[0].id


class FakeSourceRouterConfig:
    rag_source_router_llm_enabled = True
    rag_source_router_llm_min_confidence = 0.60


class FakeRouterLlm:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    def generate_json(self, **_: object) -> str:
        self.calls += 1
        import json

        return json.dumps(self.payload)
