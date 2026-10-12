from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from rag.auth.context import UserContext
from rag.connectors.models import ConnectorSchemaCatalogRecord
from rag.connectors.repositories import InMemoryConnectorProfileRepository
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.query.sources.source_resolution import (
    QuerySourceAccessError,
    list_visible_query_sources,
    public_query_source,
    query_source_id_for_catalog,
    resolve_query_source,
    source_decision_from_evidence_plan,
    selected_source_target,
    selected_source_targets,
    validate_query_source_access,
)
from rag.query.sources.source_routes import list_query_sources
from rag.query.state import initial_state
from rag.ingestion.folders.adapters.memory import InMemoryFolderScheduleRepository
from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.query.schemas import QueryRequest
from rag.query.routing.conversation_resolution import ConversationResolution
from rag.query.routing.routing_models import EvidenceNeed, EvidencePlan, SourceAssignment


def test_query_request_rejects_contradictory_source_scopes() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(query="Summarize policy", source_mode="corpus_only", query_source_id="connector_catalog:cat-1")

    with pytest.raises(ValidationError):
        QueryRequest(query="Count cases", source_mode="db_only", document_ids=["doc-1"])

    with pytest.raises(ValidationError):
        QueryRequest(query="Count cases", continue_source_clarification=True)

    with pytest.raises(ValidationError):
        QueryRequest(
            query="Compare cases",
            query_source_ids=["connector_catalog:cat-1"] * 2,
        )

    with pytest.raises(ValidationError):
        QueryRequest(
            query="Compare cases",
            query_source_id="connector_catalog:cat-1",
            query_source_ids=["connector_catalog:cat-2"],
        )


def test_explicit_multi_database_scope_preserves_all_authorized_sources() -> None:
    schedule_repo, profile_repo, first_catalog = _repos_with_sources()
    second_profile = _add_profile(
        profile_repo,
        profile_id="profile-telemetry",
        name="Telemetry warehouse",
    )
    second_catalog = _add_catalog(
        profile_repo,
        profile_id=second_profile.id,
        name="Telemetry approved database scope",
    )
    source_ids = [
        query_source_id_for_catalog(first_catalog.id),
        query_source_id_for_catalog(second_catalog.id),
    ]

    ctx = _ctx(
        QueryRequest(
            query="Compare cases with telemetry",
            source_mode="db_only",
            query_source_ids=source_ids,
        )
    )
    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.explicit is True
    assert decision.query_source_id == source_ids[0]
    assert decision.query_source_ids == tuple(source_ids)
    assert selected_source_targets(decision) == (
        ("catalog", first_catalog.id),
        ("catalog", second_catalog.id),
    )
    assert {
        item["source_id"] for item in ctx["source_candidates"]["databases"]
    } == set(source_ids)


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


def test_source_resolver_explicit_auto_scopes_remain_exact() -> None:
    schedule_repo, profile_repo, catalog = _repos_with_sources()
    kwargs = {
        "schedule_repo": schedule_repo,
        "connector_profile_repo": profile_repo,
    }

    selected = resolve_query_source(
        _ctx(QueryRequest(query="List open cases", query_source_id=query_source_id_for_catalog(catalog.id))),
        **kwargs,
    )
    document = resolve_query_source(
        _ctx(QueryRequest(query="List open cases", document_ids=["doc-1"])),
        **kwargs,
    )
    named = resolve_query_source(
        _ctx(QueryRequest(query="List open cases using Cases approved database scope")),
        **kwargs,
    )

    assert (selected.resolved_mode, selected.query_source_record_id) == ("db_only", catalog.id)
    assert document.resolved_mode == "corpus_only"
    assert (named.resolved_mode, named.query_source_record_id) == ("db_only", catalog.id)


def test_source_resolver_auto_routes_structured_schema_matches_to_hybrid() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="Count cases by status")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.reason == "auto_hybrid_all_visible_sources"
    assert decision.preferred_source == "database"
    assert decision.structured_score > 0
    assert decision.source_match_score > 0


def test_source_resolver_auto_routes_schema_term_matches_to_hybrid() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="What is the status of case CASE-2025-5002?")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.reason == "auto_hybrid_all_visible_sources"
    assert decision.preferred_source == "database"
    assert decision.structured_score == 0
    assert decision.source_match_score >= 2


def test_source_resolver_auto_routes_arbitrary_client_schema_terminology() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    profile = _add_profile(
        profile_repo,
        profile_id="profile-velan",
        name="Operational source",
    )
    catalog = _add_catalog(
        profile_repo,
        profile_id=profile.id,
        name="Vela scope",
        routing_profile={
            "entities": ["quorvans"],
            "synonyms": ["tessik phase"],
        },
    )

    decision = resolve_query_source(
        _ctx(QueryRequest(query="Which quorvans entered the tessik phase?")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.preferred_source == "database"
    assert decision.preferred_catalog_id == catalog.id
    assert decision.source_match_score >= 3


def test_source_resolver_routes_exact_connector_name_without_database_keywords() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    profile = _add_profile(
        profile_repo,
        profile_id="profile-sable",
        name="Sable source",
    )
    catalog = _add_catalog(
        profile_repo,
        profile_id=profile.id,
        name="Sable Meridian",
    )

    decision = resolve_query_source(
        _ctx(QueryRequest(query="Using Sable Meridian, which entries changed yesterday?")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "db_only"
    assert decision.reason == "inline_named_connector_source"
    assert decision.query_source_record_id == catalog.id
    assert decision.semantic_query == "which entries changed yesterday?"


def test_source_resolver_defers_tied_auto_sources_to_capability_planner() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    second_profile = _add_profile(
        profile_repo,
        profile_id="profile-case-archive",
        name="Case archive",
    )
    _add_catalog(
        profile_repo,
        profile_id=second_profile.id,
        status="approved",
        group_path="/ops",
        name="Archived cases",
    )

    ctx = _ctx(QueryRequest(query="Show cases by status"))
    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.preferred_source == "database"
    assert decision.preferred_catalog_id is None
    assert decision.database_route is None
    assert len(ctx["source_candidates"]["databases"]) == 2


def test_source_resolver_auto_routes_policy_questions_corpus_first() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()

    decision = resolve_query_source(
        _ctx(QueryRequest(query="Explain the retention policy")),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "corpus_first"
    assert decision.reason == "auto_corpus_first_corpus_preferred"
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
    assert decision.reason == "auto_hybrid_all_visible_sources"
    assert decision.structured_score > 0
    assert decision.corpus_score > 0
    assert decision.source_match_score > 0


def test_source_resolver_mixed_comparison_overrides_strong_document_preference() -> None:
    schedule_repo, profile_repo, catalog = _repos_with_sources()

    decision = resolve_query_source(
        _ctx(
            QueryRequest(
                query="Compare cases with the target in the retention manual document"
            )
        ),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=_document_repo_with_policy(),
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.query_source_record_id is None
    assert decision.preferred_catalog_id == catalog.id
    assert decision.corpus_score > 0
    assert decision.source_match_score > 0
    assert decision.document_match_score > decision.source_match_score


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

    assert decision.resolved_mode == "corpus_first"
    assert decision.reason == "auto_corpus_first_corpus_preferred"
    assert decision.preferred_source == "corpus"
    assert decision.document_match_score > 0


def test_source_resolver_records_compact_authorized_planner_candidates() -> None:
    schedule_repo, profile_repo, catalog = _repos_with_sources()
    ctx = _ctx(QueryRequest(query="Compare case totals with the retention policy"))

    resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=_document_repo_with_policy(),
    )

    candidates = ctx["source_candidates"]
    assert candidates["databases"][0]["catalog_id"] == catalog.id
    assert candidates["documents"][0]["title"] == "Retention manual"
    assert "tables" not in candidates["databases"][0]


def test_source_resolver_only_advertises_graph_when_enabled() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    disabled_ctx = _ctx(QueryRequest(query="Show relationships across sources"))
    enabled_ctx = _ctx(QueryRequest(query="Show relationships across sources"))

    resolve_query_source(
        disabled_ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        graph_enabled=False,
    )
    resolve_query_source(
        enabled_ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        graph_enabled=True,
    )

    assert disabled_ctx["source_candidates"]["graphs"] == []
    assert enabled_ctx["source_candidates"]["graphs"][0]["source_id"] == (
        "knowledge_graph"
    )


def test_explicit_catalog_scope_hides_other_sources_from_planner() -> None:
    schedule_repo, profile_repo, selected_catalog = _repos_with_sources()
    other_profile = _add_profile(
        profile_repo, profile_id="profile-other", name="Other warehouse"
    )
    _add_catalog(
        profile_repo,
        profile_id=other_profile.id,
        status="approved",
        group_path="/ops",
        name="Other scope",
    )
    ctx = _ctx(
        QueryRequest(
            query="Compare case totals",
            source_mode="hybrid",
            query_source_id=query_source_id_for_catalog(selected_catalog.id),
        )
    )

    resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=_document_repo_with_policy(),
    )

    assert [item["source_id"] for item in ctx["source_candidates"]["databases"]] == [
        query_source_id_for_catalog(selected_catalog.id)
    ]


def test_evidence_plan_materializes_multiple_authorized_connector_sources() -> None:
    schedule_repo, profile_repo, first_catalog = _repos_with_sources()
    second_profile = _add_profile(
        profile_repo, profile_id="profile-telemetry", name="Telemetry"
    )
    second_catalog = _add_catalog(
        profile_repo,
        profile_id=second_profile.id,
        status="approved",
        group_path="/ops",
        name="Telemetry scope",
    )
    ctx = _ctx(QueryRequest(query="Compare inspections with telemetry"))
    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )
    plan = EvidencePlan(
        needs=(
            EvidenceNeed(
                id="inspection",
                query="inspection result",
                assignments=(
                    SourceAssignment(
                        source_id=query_source_id_for_catalog(first_catalog.id),
                        capability="connector_query",
                    ),
                ),
            ),
            EvidenceNeed(
                id="telemetry",
                query="telemetry result",
                assignments=(
                    SourceAssignment(
                        source_id=query_source_id_for_catalog(second_catalog.id),
                        capability="connector_query",
                    ),
                ),
            ),
        )
    )

    materialized = source_decision_from_evidence_plan(
        decision, plan, ctx["source_candidates"]
    )

    assert materialized.resolved_mode == "db_only"
    assert selected_source_targets(materialized) == (
        ("catalog", first_catalog.id),
        ("catalog", second_catalog.id),
    )


def test_explicit_source_followup_reuses_authorized_document_scope() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    document_repo = _document_repo_with_policy()
    ctx = _ctx(QueryRequest(query="What else does that document say?"))
    ctx["session_turns"] = [
        {
            "turn_id": "policy-turn",
            "query": "What is the retention period?",
            "answer": "The manual specifies a retention period.",
            "sources": [
                {"doc_id": "doc-policy", "doc_title": "Retention manual"}
            ],
        }
    ]
    ctx["conversation_resolution"] = ConversationResolution(
        relation="follow_up",
        effective_query="What else does the Retention manual say?",
        clarification_question=None,
        method="ai_assisted",
        context_turn_count=1,
        antecedent_turn_ids=("policy-turn",),
        dependency_targets=("source",),
    )
    ctx["effective_query"] = "What else does the Retention manual say?"

    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=document_repo,
    )

    assert decision.reason == "session_document_source"
    assert decision.resolved_mode == "corpus_only"
    assert decision.inherited_document_ids == ("doc-policy",)


def test_source_resolver_auto_prefers_matching_manual_over_generic_list_signal() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    document_repo = _document_repo_with_samsung_manual()

    decision = resolve_query_source(
        _ctx(
            QueryRequest(
                query="Give me a list of all the equipment required to repair a Samsung device. Do not skip or miss any."
            )
        ),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=document_repo,
    )

    assert decision.resolved_mode == "corpus_first"
    assert decision.reason == "auto_corpus_first_corpus_preferred"
    assert decision.preferred_source == "corpus"
    assert decision.structured_score == 1
    assert decision.source_match_score == 0
    assert decision.document_match_score >= 2


def test_source_resolver_routes_samsung_tool_count_to_documents() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    second_profile = _add_profile(
        profile_repo,
        profile_id="profile-orders",
        name="Orders warehouse",
    )
    _add_catalog(
        profile_repo,
        profile_id=second_profile.id,
        name="Orders approved database scope",
    )

    decision = resolve_query_source(
        _ctx(
            QueryRequest(
                query=(
                    "How many disassembly and assembly tools are listed in the "
                    "Samsung repair manual, and what is each tool used for?"
                )
            )
        ),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        document_repo=_document_repo_with_samsung_manual(),
    )

    assert decision.resolved_mode == "corpus_first"
    assert decision.preferred_source == "corpus"
    assert decision.source_match_score == 0
    assert decision.document_match_score >= 4
    assert decision.database_route is None


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
    ctx["conversation_resolution"] = ConversationResolution(
        relation="follow_up",
        effective_query="Which pending cases are open?",
        clarification_question=None,
        method="ai_assisted",
        context_turn_count=1,
        dependency_targets=("result",),
    )
    ctx["effective_query"] = "Which pending cases are open?"

    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.resolved_mode == "hybrid"
    assert decision.preferred_source == "database"
    assert "db_score" in decision.signal_reason


def test_source_resolver_followup_reuses_previous_authorized_database() -> None:
    schedule_repo, profile_repo, catalog = _repos_with_sources()
    second_profile = _add_profile(
        profile_repo, profile_id="profile-orders", name="Orders warehouse"
    )
    second_catalog = _add_catalog(
        profile_repo,
        profile_id=second_profile.id,
        status="approved",
        group_path="/ops",
        name="Orders scope",
    )
    ctx = _ctx(QueryRequest(query="What about pending ones?"))
    ctx["session_turns"] = [
        {
            "turn_id": "cases-turn",
            "query": "Which cases are open?",
            "answer": "Open cases...",
            "source_mode": "db_only",
            "query_source_id": query_source_id_for_catalog(catalog.id),
        },
        {
            "turn_id": "orders-turn",
            "query": "Which orders shipped?",
            "answer": "Shipped orders...",
            "source_mode": "db_only",
            "query_source_id": query_source_id_for_catalog(second_catalog.id),
        },
    ]
    ctx["conversation_resolution"] = ConversationResolution(
        relation="follow_up",
        effective_query="Which pending cases are open?",
        clarification_question=None,
        method="ai_assisted",
        context_turn_count=2,
        antecedent_turn_ids=("cases-turn",),
        dependency_targets=("result",),
    )
    ctx["effective_query"] = "Which pending cases are open?"

    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.reason == "session_database_source"
    assert decision.query_source_record_id == catalog.id
    assert decision.router_mode == "deterministic"


def test_topic_followup_does_not_hard_reuse_previous_database() -> None:
    schedule_repo, profile_repo, catalog = _repos_with_sources()
    second_profile = _add_profile(
        profile_repo, profile_id="profile-orders", name="Orders warehouse"
    )
    _add_catalog(
        profile_repo,
        profile_id=second_profile.id,
        status="approved",
        group_path="/ops",
        name="Orders scope",
    )
    ctx = _ctx(QueryRequest(query="What does the policy say?"))
    ctx["session_turns"] = [
        {
            "query": "Which cases are open?",
            "answer": "Open cases...",
            "source_mode": "db_only",
            "query_source_id": query_source_id_for_catalog(catalog.id),
        }
    ]
    ctx["conversation_resolution"] = ConversationResolution(
        relation="follow_up",
        effective_query="What does the leave policy say?",
        clarification_question=None,
        method="ai_assisted",
        context_turn_count=1,
        dependency_targets=("query",),
    )
    ctx["effective_query"] = "What does the leave policy say?"

    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.reason != "session_database_source"
    assert decision.query_source_record_id != catalog.id


def test_short_new_topic_does_not_inherit_previous_source_bias() -> None:
    schedule_repo, profile_repo, _catalog = _repos_with_sources()
    ctx = _ctx(QueryRequest(query="Reset MFA"))
    ctx["session_turns"] = [
        {
            "query": "Which cases are open?",
            "answer": "Open cases...",
            "source_mode": "db_only",
            "sources": [{"doc_id": "connector-live-scope:catalog"}],
        }
    ]
    ctx["conversation_resolution"] = ConversationResolution(
        relation="new_topic",
        effective_query="Reset MFA",
        clarification_question=None,
        method="ai_assisted",
        context_turn_count=1,
    )

    decision = resolve_query_source(
        ctx,
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
    )

    assert decision.preferred_source != "database"


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
    routing_profile: dict[str, list[str]] | None = None,
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
            "routing_profile": routing_profile or {},
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


def _document_repo_with_samsung_manual() -> InMemoryDocumentRepository:
    repo = InMemoryDocumentRepository()
    document = repo.create_document(
        document_id="doc-samsung-repair",
        title="Samsung device repair manual",
        source_id="samsung-repair-manual.pdf",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="repair manual",
        effective_date=None,
        expiry_date=None,
        description="Samsung device disassembly, assembly, tools, and repair equipment",
        pending_supersedes=[],
        content_hash="hash-samsung-repair",
        uploaded_by="user",
        file_path="/tmp/samsung-repair-manual.pdf",
        ingest_status="completed",
    )
    repo.save_document_metadata(
        document_id=document.id,
        summary="Samsung device repair equipment and procedures.",
        language="en",
        topics=["Samsung", "repair", "equipment"],
        llm_topics=["device repair"],
        doc_type="repair manual",
        auto_doc_type="manual",
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
