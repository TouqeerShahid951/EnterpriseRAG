from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Event

import pytest

from rag.auth.context import UserContext
from rag.connectors.crypto import encrypt_secret, keyring_from_settings
from rag.connectors.models import ConnectorQueryResult
from rag.connectors.registry import default_connector_registry
from rag.query.sources.live_sql import retrieve_live_sql_hits
from rag.query.cancellation import QueryCancelled
from rag.query.qdrant import SearchHit
from rag.query.routing.routing_models import RoutePlan
from rag.query.sources.source_resolution import SourceDecision
from rag.query.sources import sources_from_hits
from rag.query.state import initial_state
from rag.connectors.repositories import InMemoryConnectorProfileRepository
from rag.ingestion.folders.adapters.memory import InMemoryFolderScheduleRepository
from rag.retrieval.service import RetrievalService
from rag.query.schemas import QueryRequest


@dataclass
class FakeConfig:
    connector_live_sql_enabled: bool = True
    connector_live_sql_max_rows: int = 2
    connector_live_sql_timeout_seconds: int = 15
    connector_live_sql_max_scopes: int = 5
    connector_live_sql_max_repair_attempts: int = 2
    connector_live_sql_result_verifier_enabled: bool = False
    connector_live_sql_verifier_sample_rows: int = 5
    connector_secrets_key: str = "replace-with-local-connector-secrets-key"
    connector_secrets_key_ring: str = ""
    connector_include_stale_in_retrieval: bool = False
    rag_top_k: int = 10
    rag_sparse_model: str = ""
    rag_sparse_cache_dir: str = ""


class FakeLlm:
    def __init__(self, response: str = '{"sql":"SELECT id, status FROM fake.records ORDER BY id"}') -> None:
        self.response = response
        self.generated_prompts: list[str] = []
        self.generated_models: list[str | None] = []

    def generate_json(self, *, prompt: str, model: str | None, system: str, cancellation_token=None) -> str:
        _ = system, cancellation_token
        self.generated_prompts.append(prompt)
        self.generated_models.append(model)
        return self.response

    def embed(self, text: str, *, cancellation_token=None) -> list[float]:
        _ = text, cancellation_token
        return [0.1, 0.2, 0.3]


class SequenceLlm(FakeLlm):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(responses[0])
        self.responses = responses
        self.index = 0

    def generate_json(self, *, prompt: str, model: str | None, system: str, cancellation_token=None) -> str:
        _ = system, cancellation_token
        self.generated_prompts.append(prompt)
        self.generated_models.append(model)
        response = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        return response


class FakeQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]) -> list[SearchHit]:
        _ = qdrant_filter
        return [
            SearchHit(
                point_id="indexed:1",
                score=0.2,
                payload={
                    "doc_id": "indexed",
                    "chunk_id": "indexed:1",
                    "doc_title": "Indexed connector snapshot",
                    "text": "Indexed fallback evidence.",
                    "group_path": "/ops",
                    "clearance_level": "NATO_RESTRICTED",
                    "is_current": True,
                },
            )
        ][:limit]


class FailingConnector:
    connector_type = "fake"

    def execute_query(self, **kwargs):
        _ = kwargs
        raise RuntimeError("database unavailable")


class FailingRegistry:
    def get(self, _connector_type: str):
        return FailingConnector()


class FlakyConnector:
    connector_type = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def execute_query(self, *, config, secrets, query, row_limit, timeout_seconds):
        _ = secrets, timeout_seconds
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("relation temporarily unavailable; password=secret")
        rows = [item for item in config.get("live_query_rows", []) if isinstance(item, dict)]
        bounded = rows[: max(1, row_limit)]
        columns = sorted({key for row in bounded for key in row})
        return ConnectorQueryResult(query=query, columns=columns, rows=bounded)


class FlakyRegistry:
    def __init__(self) -> None:
        self.connector = FlakyConnector()

    def get(self, _connector_type: str):
        return self.connector


class QueryAwareConnector:
    connector_type = "fake"

    def __init__(self) -> None:
        self.calls = 0
        self.queries: list[str] = []

    def execute_query(self, *, config, secrets, query, row_limit, timeout_seconds):
        _ = config, secrets, timeout_seconds
        self.calls += 1
        self.queries.append(query)
        if "COUNT" in query.upper():
            rows = [{"status": "open", "total": 2}, {"status": "closed", "total": 1}]
        else:
            rows = [{"status": "open"}, {"status": "closed"}, {"status": "open"}]
        bounded = rows[: max(1, row_limit)]
        columns = list(bounded[0]) if bounded else []
        return ConnectorQueryResult(query=query, columns=columns, rows=bounded)


class QueryAwareRegistry:
    def __init__(self) -> None:
        self.connector = QueryAwareConnector()

    def get(self, _connector_type: str):
        return self.connector


def test_live_sql_retrieval_returns_fresh_connector_evidence() -> None:
    profile_repo = _repo_with_approved_catalog(
        live_rows=[
            {"id": "1", "status": "open", "amount": 10},
            {"id": "2", "status": "closed", "amount": 20},
            {"id": "3", "status": "open", "amount": 30},
        ],
    )
    ctx = _ctx("List all live case statuses")
    result = retrieve_live_sql_hits(
        ctx,
        config=FakeConfig(),
        llm=FakeLlm(),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )

    assert result.mode == "ai_assisted"
    assert len(result.hits) == 2
    assert result.hits[0].payload["doc_id"].startswith("connector-live-scope:")
    assert result.hits[0].payload["source_type"] == "connector_live_sql_database_scope"
    assert result.hits[0].payload["live_sql_scope"] == "database_scope"
    assert "fake.records" in result.hits[0].payload["live_sql"]
    assert "open" in result.hits[0].payload["text"]
    assert set(ctx["retrieval_phase_timings_ms"]) == {
        "sql_generation",
        "sql_execution",
        "sql_verification",
    }

    sources = sources_from_hits(result.hits, query=ctx["request"].query)
    assert sources[0].doc_title == "Live connector query: Fake cases approved database scope"
    assert sources[0].excerpt
    assert sources[0].attribution_kind == "table_row"
    fields = [(field.label, field.value) for field in sources[0].attribution_fields]
    assert dict(fields) == {"id": "1", "status": "open", "amount": "10"}


def test_live_sql_generation_uses_its_configured_model() -> None:
    llm = FakeLlm()

    result = retrieve_live_sql_hits(
        _ctx("List all live case statuses"),
        config=FakeConfig(),
        llm=llm,
        reasoning_model="general-reasoning",
        sql_generation_model="sql-specialist",
        connector_profile_repo=_repo_with_approved_catalog(),
        connector_registry=default_connector_registry(),
    )

    assert result.mode == "ai_assisted"
    assert llm.generated_models == ["sql-specialist"]


def test_live_sql_retrieval_respects_catalog_visibility_and_ignores_legacy_schedules() -> None:
    profile_repo = _repo_with_approved_catalog(group_path="/ops")
    hidden_ctx = _ctx("List all live case statuses", group_paths=("/other",))
    hidden = retrieve_live_sql_hits(
        hidden_ctx,
        config=FakeConfig(),
        llm=FakeLlm(),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )
    assert hidden.mode == "skipped"
    assert hidden.detail == "no_approved_connector_scope"

    legacy_schedule_repo, legacy_profile_repo = _repos_with_schedule()
    legacy = retrieve_live_sql_hits(
        _ctx("List all live case statuses"),
        config=FakeConfig(),
        llm=FakeLlm(),
        schedule_repo=legacy_schedule_repo,
        connector_profile_repo=legacy_profile_repo,
        connector_registry=default_connector_registry(),
    )
    assert legacy.mode == "skipped"
    assert legacy.detail == "no_approved_connector_scope"


def test_live_sql_retrieval_allows_catalog_shared_to_user_space() -> None:
    profile_repo = _repo_with_approved_catalog(group_path="/ops", shared_group_paths=["/finance"])
    result = retrieve_live_sql_hits(
        _ctx("List all live case statuses", group_paths=("/finance",)),
        config=FakeConfig(),
        llm=FakeLlm(),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )

    assert result.mode == "ai_assisted"
    assert result.hits[0].payload["group_path"] == "/finance"
    assert result.hits[0].payload["acl_group_paths"] == ["/ops", "/finance"]


def test_live_sql_generation_and_execution_fail_closed_to_fallback() -> None:
    profile_repo = _repo_with_approved_catalog()

    bad_json = retrieve_live_sql_hits(
        _ctx("List all live case statuses"),
        config=FakeConfig(),
        llm=FakeLlm("{}"),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )
    assert bad_json.mode == "fallback"
    assert bad_json.hits == []

    unsafe_sql = retrieve_live_sql_hits(
        _ctx("List all live case statuses"),
        config=FakeConfig(),
        llm=FakeLlm('{"sql":"SELECT * FROM fake.records"}'),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )
    assert unsafe_sql.mode == "fallback"
    assert unsafe_sql.hits == []

    connector_failure = retrieve_live_sql_hits(
        _ctx("List all live case statuses"),
        config=FakeConfig(),
        llm=FakeLlm(),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=FailingRegistry(),
    )
    assert connector_failure.mode == "fallback"
    assert connector_failure.hits == []


def test_corpus_only_blocks_planned_live_sql() -> None:
    ctx = _ctx("Count current cases", structured=False, live_sql=True)
    ctx["source_decision"] = SourceDecision(
        requested_mode="corpus_only",
        resolved_mode="corpus_only",
        semantic_query=ctx["request"].query,
        explicit=True,
        reason="composer_selected_corpus",
    )
    llm = FakeLlm()

    result = retrieve_live_sql_hits(
        ctx,
        config=FakeConfig(),
        llm=llm,
        connector_profile_repo=_repo_with_approved_catalog(),
        connector_registry=default_connector_registry(),
    )

    assert result.mode == "skipped"
    assert result.detail == "live_sql_not_selected"
    assert llm.generated_prompts == []


def test_explicit_hybrid_runs_live_sql_without_planner_capability() -> None:
    ctx = _ctx("Compare selected sources", structured=False, live_sql=False)
    ctx["source_decision"] = SourceDecision(
        requested_mode="hybrid",
        resolved_mode="hybrid",
        semantic_query=ctx["request"].query,
        explicit=True,
        reason="composer_selected_hybrid",
    )

    result = retrieve_live_sql_hits(
        ctx,
        config=FakeConfig(),
        llm=FakeLlm(),
        connector_profile_repo=_repo_with_approved_catalog(),
        connector_registry=default_connector_registry(),
    )

    assert result.mode == "ai_assisted"
    assert result.hits


def test_document_table_settings_do_not_run_sql_but_explicit_database_does() -> None:
    schedule_repo = InMemoryFolderScheduleRepository()
    profile_repo = _repo_with_approved_catalog(live_rows=[{"id": "1", "status": "open"}])
    llm = FakeLlm()
    service = RetrievalService(
        config=FakeConfig(),
        embedder=llm,
        vector_store=FakeQdrant(),
        schedule_repo=schedule_repo,
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )
    structured_ctx = _ctx(
        "What is the reference number in the indexed offer letter?",
        live_sql=False,
    )
    structured_ctx["source_decision"] = SourceDecision(
        requested_mode="auto",
        resolved_mode="hybrid",
        semantic_query=structured_ctx["request"].query,
        explicit=False,
        reason="auto_hybrid_all_visible_sources",
    )
    structured_hits = service.retrieve(structured_ctx)

    assert [hit.payload["doc_id"] for hit in structured_hits] == ["indexed"]
    assert structured_ctx["execution_modes"]["live_sql_retriever"] == "skipped"
    assert len(llm.generated_prompts) == 0

    factual_ctx = _ctx("What is the indexed fallback?", structured=False)
    factual_hits = service.retrieve(factual_ctx)

    assert [hit.payload["doc_id"] for hit in factual_hits] == ["indexed"]
    assert factual_ctx["execution_modes"]["live_sql_retriever"] == "skipped"
    assert len(llm.generated_prompts) == 0

    db_factual_ctx = _ctx("What is the status of ticket TCK-2025-5002?", structured=False)
    db_factual_ctx["source_decision"] = SourceDecision(
        requested_mode="db_only",
        resolved_mode="db_only",
        semantic_query=db_factual_ctx["request"].query,
        explicit=True,
        reason="composer_selected_database",
        allow_source_expansion=False,
    )
    db_factual_hits = service.retrieve(db_factual_ctx)

    assert db_factual_hits[0].payload["source_type"] == "connector_live_sql_database_scope"
    assert db_factual_ctx["execution_modes"]["live_sql_retriever"] == "ai_assisted"
    assert len(llm.generated_prompts) == 1


def test_retrieval_service_hybrid_corpus_preference_keeps_live_sql_after_vector_hits() -> None:
    profile_repo = _repo_with_approved_catalog(live_rows=[{"id": "1", "status": "open"}])
    llm = FakeLlm()
    service = RetrievalService(
        config=FakeConfig(),
        embedder=llm,
        vector_store=FakeQdrant(),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )
    ctx = _ctx("What is the status?", structured=False, live_sql=True)
    ctx["source_decision"] = SourceDecision(
        requested_mode="auto",
        resolved_mode="hybrid",
        semantic_query=ctx["request"].query,
        explicit=False,
        reason="auto_hybrid_corpus_preferred",
        allow_source_expansion=False,
        preferred_source="corpus",
    )

    hits = service.retrieve(ctx)

    assert hits[0].payload["doc_id"] == "indexed"
    assert hits[1].payload["source_type"] == "connector_live_sql_database_scope"
    assert ctx["execution_modes"]["live_sql_retriever"] == "ai_assisted"
    assert "hybrid_parallel" in ctx["execution_details"]["source_resolver"]


def test_retrieval_service_runs_unexpanded_hybrid_branches_in_parallel(monkeypatch) -> None:
    service = RetrievalService(
        config=FakeConfig(),
        embedder=FakeLlm(),
        vector_store=FakeQdrant(),
    )
    ctx = _ctx("Compare the live status with the indexed policy", structured=False)
    ctx["source_decision"] = SourceDecision(
        requested_mode="hybrid",
        resolved_mode="hybrid",
        semantic_query=ctx["request"].query,
        explicit=True,
        reason="composer_selected_hybrid",
        preferred_source="corpus",
    )
    live_started = Event()
    vector_started = Event()
    live_hit = SearchHit(
        point_id="live:1",
        score=1.0,
        payload={"doc_id": "connector-live-scope:test", "chunk_id": "live:1"},
    )
    vector_hit = SearchHit(
        point_id="vector:1",
        score=1.0,
        payload={"doc_id": "indexed", "chunk_id": "vector:1"},
    )

    def retrieve_live(branch_ctx):
        assert branch_ctx["execution_modes"] is not ctx["execution_modes"]
        branch_ctx["execution_modes"]["live_sql_retriever"] = "ai_assisted"
        branch_ctx["retrieval_phase_timings_ms"] = {"sql_execution": 7}
        live_started.set()
        assert vector_started.wait(1)
        return [live_hit]

    def retrieve_vector(branch_ctx):
        assert branch_ctx["execution_details"] is not ctx["execution_details"]
        branch_ctx["retrieval_phase_timings_ms"] = {
            "embeddings": 3,
            "vector_search": 4,
        }
        branch_ctx["degraded"] = True
        branch_ctx["degraded_reason"] = "vector_scope_partial"
        vector_started.set()
        assert live_started.wait(1)
        return [vector_hit]

    monkeypatch.setattr(service, "_retrieve_live_sql", retrieve_live)
    monkeypatch.setattr(service, "_retrieve_vector", retrieve_vector)

    hits = service.retrieve(ctx)

    assert hits == [vector_hit, live_hit]
    assert ctx["execution_modes"]["live_sql_retriever"] == "ai_assisted"
    assert ctx["degraded_reason"] == "vector_scope_partial"
    assert ctx["retrieval_phase_timings_ms"] == {
        "embeddings": 3,
        "vector_search": 4,
        "sql_execution": 7,
    }


def test_retrieval_service_propagates_hybrid_branch_cancellation(monkeypatch) -> None:
    service = RetrievalService(
        config=FakeConfig(),
        embedder=FakeLlm(),
        vector_store=FakeQdrant(),
    )
    ctx = _ctx("Compare live and indexed evidence", structured=False)
    ctx["source_decision"] = SourceDecision(
        requested_mode="hybrid",
        resolved_mode="hybrid",
        semantic_query=ctx["request"].query,
        explicit=True,
        reason="composer_selected_hybrid",
    )

    def cancel_live(_branch_ctx):
        raise QueryCancelled()

    monkeypatch.setattr(service, "_retrieve_live_sql", cancel_live)
    monkeypatch.setattr(service, "_retrieve_vector", lambda _branch_ctx: [])

    with pytest.raises(QueryCancelled):
        service.retrieve(ctx)


def test_retrieval_service_corpus_primary_skips_live_sql() -> None:
    profile_repo = _repo_with_approved_catalog(live_rows=[{"id": "1", "status": "open"}])
    llm = FakeLlm()
    service = RetrievalService(
        config=FakeConfig(),
        embedder=llm,
        vector_store=FakeQdrant(),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )
    ctx = _ctx("List the equipment in the Samsung repair manual", structured=False)
    ctx["source_decision"] = SourceDecision(
        requested_mode="auto",
        resolved_mode="corpus_first",
        semantic_query=ctx["request"].query,
        explicit=False,
        reason="auto_corpus_first_corpus_preferred",
        preferred_source="corpus",
        routing_confidence=0.9,
    )

    hits = service.retrieve(ctx)

    assert [item.payload["doc_id"] for item in hits] == ["indexed"]
    assert ctx["execution_modes"]["live_sql_retriever"] == "skipped"
    assert llm.generated_prompts == []


def test_retrieval_service_corpus_expansion_reuses_primary_without_vector_rerun() -> None:
    class CountingQdrant(FakeQdrant):
        def __init__(self) -> None:
            self.search_calls = 0

        def search(
            self,
            vector: list[float],
            *,
            limit: int,
            qdrant_filter: dict[str, object],
        ) -> list[SearchHit]:
            self.search_calls += 1
            return super().search(
                vector,
                limit=limit,
                qdrant_filter=qdrant_filter,
            )

    profile_repo = _repo_with_approved_catalog(
        live_rows=[{"id": "1", "status": "open"}]
    )
    llm = FakeLlm()
    qdrant = CountingQdrant()
    service = RetrievalService(
        config=FakeConfig(),
        embedder=llm,
        vector_store=qdrant,
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )
    ctx = _ctx("What is the status of case 1?", structured=False, live_sql=True)
    decision = SourceDecision(
        requested_mode="auto",
        resolved_mode="corpus_first",
        semantic_query=ctx["request"].query,
        explicit=False,
        reason="auto_corpus_first_corpus_preferred",
        preferred_source="corpus",
        routing_confidence=0.9,
    )
    ctx["source_decision"] = decision

    primary_hits = service.retrieve(ctx)

    assert [item.payload["doc_id"] for item in primary_hits] == ["indexed"]
    assert qdrant.search_calls == 1
    assert llm.generated_prompts == []

    ctx["source_primary_hits"] = primary_hits
    ctx["source_expansion_from"] = "corpus_first"
    ctx["source_decision"] = replace(
        decision,
        resolved_mode="hybrid",
        reason=f"{decision.reason}:evidence_expansion",
    )
    expanded_hits = service.retrieve(ctx)

    assert len(expanded_hits) == 2
    assert expanded_hits[0].payload["doc_id"] == "indexed"
    assert expanded_hits[1].payload["source_type"] == (
        "connector_live_sql_database_scope"
    )
    assert qdrant.search_calls == 1
    assert len(llm.generated_prompts) == 1


def test_retrieval_service_expansion_reuses_database_primary_hits() -> None:
    profile_repo = _repo_with_approved_catalog(live_rows=[{"id": "1", "status": "open"}])
    llm = FakeLlm()
    service = RetrievalService(
        config=FakeConfig(),
        embedder=llm,
        vector_store=FakeQdrant(),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )
    ctx = _ctx("What is the status of case 1?", structured=False, live_sql=True)
    decision = SourceDecision(
        requested_mode="auto",
        resolved_mode="db_first",
        semantic_query=ctx["request"].query,
        explicit=False,
        reason="auto_db_first_database_preferred",
        preferred_source="database",
        routing_confidence=0.9,
    )
    ctx["source_decision"] = decision

    primary_hits = service.retrieve(ctx)

    assert len(primary_hits) == 1
    assert primary_hits[0].payload["source_type"] == "connector_live_sql_database_scope"
    assert len(llm.generated_prompts) == 1

    ctx["source_primary_hits"] = primary_hits
    ctx["source_expansion_from"] = "db_first"
    ctx["source_decision"] = replace(
        decision,
        resolved_mode="hybrid",
        reason=f"{decision.reason}:evidence_expansion",
    )
    expanded_hits = service.retrieve(ctx)

    assert [item.payload["doc_id"] for item in expanded_hits] == [
        primary_hits[0].payload["doc_id"],
        "indexed",
    ]
    assert len(llm.generated_prompts) == 1


def test_live_sql_retrieval_uses_approved_database_scope_without_schedule() -> None:
    profile_repo = _repo_with_approved_catalog(
        live_rows=[{"status": "open", "total": 2}],
    )
    ctx = _ctx("Count cases by status")
    llm = FakeLlm('{"sql":"SELECT status, COUNT(*) AS total FROM fake.records GROUP BY status"}')

    result = retrieve_live_sql_hits(
        ctx,
        config=FakeConfig(),
        llm=llm,
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )

    assert result.mode == "ai_assisted"
    assert "scope=database_scope" in result.detail
    assert len(result.hits) == 1
    assert result.hits[0].payload["source_type"] == "connector_live_sql_database_scope"
    assert result.hits[0].payload["live_sql_scope"] == "database_scope"
    assert result.hits[0].payload["connector_schema_catalog_id"]
    assert "LIMIT" in result.hits[0].payload["live_sql"].upper()
    assert "open" in result.hits[0].payload["text"]


def test_live_sql_repairs_after_catalog_validation_error() -> None:
    profile_repo = _repo_with_approved_catalog(live_rows=[{"status": "open"}])
    llm = SequenceLlm(
        [
            '{"sql":"SELECT * FROM fake.records"}',
            '{"sql":"SELECT status FROM fake.records"}',
        ]
    )

    result = retrieve_live_sql_hits(
        _ctx("List case statuses"),
        config=FakeConfig(),
        llm=llm,
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )

    assert result.mode == "ai_assisted"
    assert "repairs=1" in result.detail
    assert len(llm.generated_prompts) == 2
    assert "Previous failure stage: validation" in llm.generated_prompts[1]
    assert "SELECT * FROM fake.records" in llm.generated_prompts[1]
    assert result.hits[0].payload["live_sql_scope"] == "database_scope"
    assert "SELECT status FROM fake.records" in result.hits[0].payload["live_sql"]


def test_live_sql_repairs_after_connector_execution_error() -> None:
    profile_repo = _repo_with_approved_catalog(live_rows=[{"status": "open"}])
    llm = SequenceLlm(
        [
            '{"sql":"SELECT status FROM fake.records"}',
            '{"sql":"SELECT status FROM fake.records"}',
        ]
    )
    registry = FlakyRegistry()

    result = retrieve_live_sql_hits(
        _ctx("List case statuses"),
        config=FakeConfig(),
        llm=llm,
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=registry,
    )

    assert result.mode == "ai_assisted"
    assert "repairs=1" in result.detail
    assert registry.connector.calls == 2
    assert len(llm.generated_prompts) == 2
    assert "Previous failure stage: execution" in llm.generated_prompts[1]
    assert "secret" not in llm.generated_prompts[1].lower()
    assert result.hits[0].payload["structured_fields"][0]["value"] == "open"


def test_live_sql_repairs_after_result_verifier_rejects_shape() -> None:
    profile_repo = _repo_with_approved_catalog()
    llm = SequenceLlm(
        [
            '{"sql":"SELECT status FROM fake.records"}',
            '{"verdict":"repair","reason":"The question asks for counts by status, but the result only returns statuses.","repair_instruction":"Return status and COUNT(*) grouped by status."}',
            '{"sql":"SELECT status, COUNT(*) AS total FROM fake.records GROUP BY status"}',
            '{"verdict":"accept","reason":"The result includes status groups and totals."}',
        ]
    )
    registry = QueryAwareRegistry()

    result = retrieve_live_sql_hits(
        _ctx("Count cases by status"),
        config=FakeConfig(connector_live_sql_result_verifier_enabled=True),
        llm=llm,
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=registry,
    )

    assert result.mode == "ai_assisted"
    assert "repairs=1" in result.detail
    assert registry.connector.calls == 2
    assert len(llm.generated_prompts) == 4
    assert "Verify whether this already-safe live SQL result shape" in llm.generated_prompts[1]
    assert "Previous failure stage: verification" in llm.generated_prompts[2]
    assert "SELECT status FROM fake.records" in llm.generated_prompts[2]
    assert result.hits[0].payload["structured_field_names"] == ["status", "total"]
    assert result.hits[0].payload["structured_fields"][1]["value"] == "2"


def test_live_sql_result_verifier_bad_json_accepts_existing_result() -> None:
    profile_repo = _repo_with_approved_catalog()
    llm = SequenceLlm(
        [
            '{"sql":"SELECT status, COUNT(*) AS total FROM fake.records GROUP BY status"}',
            "not json",
        ]
    )
    registry = QueryAwareRegistry()

    result = retrieve_live_sql_hits(
        _ctx("Count cases by status"),
        config=FakeConfig(connector_live_sql_result_verifier_enabled=True),
        llm=llm,
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=registry,
    )

    assert result.mode == "ai_assisted"
    assert "repairs=0" in result.detail
    assert registry.connector.calls == 1
    assert len(llm.generated_prompts) == 2
    assert result.hits[0].payload["structured_field_names"] == ["status", "total"]


def test_live_sql_retrieval_requires_approved_database_scope() -> None:
    profile_repo = _repo_with_approved_catalog(status="reviewed")

    result = retrieve_live_sql_hits(
        _ctx("Count cases by status"),
        config=FakeConfig(),
        llm=FakeLlm('{"sql":"SELECT status FROM fake.records"}'),
        schedule_repo=InMemoryFolderScheduleRepository(),
        connector_profile_repo=profile_repo,
        connector_registry=default_connector_registry(),
    )

    assert result.mode == "skipped"
    assert result.detail == "no_approved_connector_scope"


def _repos_with_schedule(
    *,
    live_rows: list[dict[str, object]] | None = None,
    group_path: str = "/ops",
    status: str = "active",
    schedule_row_limit: int = 100,
) -> tuple[InMemoryFolderScheduleRepository, InMemoryConnectorProfileRepository]:
    schedule_repo = InMemoryFolderScheduleRepository()
    profile_repo = InMemoryConnectorProfileRepository()
    profile = profile_repo.create_profile(
        name="Fake cases",
        connector_type="fake",
        public_config={
            "live_query_rows": live_rows or [{"id": "1", "status": "open"}],
        },
        encrypted_secrets=encrypt_secret({}, keyring_from_settings(FakeConfig.connector_secrets_key)),
        created_by="user",
    )
    schedule_repo.create_schedule(
        name="Case schedule",
        source_type="connector",
        schedule_type="recurring",
        status=status,
        group_path=group_path,
        clearance_level="NATO_RESTRICTED",
        doc_type="case record",
        effective_date=None,
        expiry_date=None,
        description="Approved case rows",
        timezone="Asia/Karachi",
        scheduled_at=None,
        recurrence={},
        source_config={
            "connector_profile_id": profile.id,
            "connector_type": "fake",
            "selection": {
                "query": "SELECT id, status, amount FROM fake.records",
                "row_limit": schedule_row_limit,
            },
            "identity_fields": ["id"],
            "row_limit": schedule_row_limit,
        },
        created_by="user",
        next_run_at=None,
    )
    return schedule_repo, profile_repo


def _repo_with_approved_catalog(
    *,
    live_rows: list[dict[str, object]] | None = None,
    status: str = "approved",
    group_path: str = "/ops",
    shared_group_paths: list[str] | None = None,
) -> InMemoryConnectorProfileRepository:
    profile_repo = InMemoryConnectorProfileRepository()
    profile = profile_repo.create_profile(
        name="Fake cases",
        connector_type="fake",
        public_config={
            "live_query_rows": live_rows or [{"status": "open", "total": 1}],
        },
        encrypted_secrets=encrypt_secret({}, keyring_from_settings(FakeConfig.connector_secrets_key)),
        created_by="user",
    )
    profile_repo.save_schema_catalog(
        profile_id=profile.id,
        connector_type="fake",
        status=status,
        group_path=group_path,
        clearance_level="NATO_RESTRICTED",
        created_by="user",
        approved_by="user" if status == "approved" else None,
        catalog_json={
            "version": 1,
            "name": "Fake cases approved database scope",
            "row_limit": 50,
            "shared_group_paths": shared_group_paths or [],
            "tables": [
                {
                    "key": "fake.records",
                    "schema": "fake",
                    "name": "records",
                    "allowed": True,
                    "sensitive": False,
                    "columns": [
                        {"name": "id", "data_type": "text", "allowed": True, "sensitive": False},
                        {"name": "status", "data_type": "text", "allowed": True, "sensitive": False},
                        {"name": "amount", "data_type": "integer", "allowed": True, "sensitive": False},
                    ],
                }
            ],
            "relationships": [],
        },
    )
    return profile_repo


def _ctx(
    query: str,
    *,
    group_paths: tuple[str, ...] = ("/ops",),
    structured: bool = True,
    live_sql: bool | None = None,
):
    if live_sql is None:
        live_sql = structured
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user",
            email="user@example.test",
            group_paths=group_paths,
            clearance_level="NATO_RESTRICTED",
        ),
        started=0.0,
    )
    ctx["route_plan"] = RoutePlan(
        original_query=query,
        resolved_query=query,
        intent="aggregation" if structured else "factual_simple",
        capabilities=("general_search", "live_sql") if live_sql else ("general_search",),
        public_intent="aggregation" if structured else "factual_simple",
        use_structured_query=structured,
        search_mode="structured_first" if structured else "hybrid",
        top_k=10,
    )
    return ctx
