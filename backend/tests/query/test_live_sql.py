from __future__ import annotations

from dataclasses import dataclass

from rag.auth.context import UserContext
from rag.connectors.crypto import encrypt_secret, keyring_from_settings
from rag.connectors.models import ConnectorQueryResult
from rag.connectors.registry import default_connector_registry
from rag.query.live_sql import retrieve_live_sql_hits
from rag.query.qdrant import SearchHit
from rag.query.routing_models import RoutePlan
from rag.query.source_resolution import SourceDecision
from rag.query.sources import sources_from_hits
from rag.query.state import initial_state
from rag.connectors.repositories import InMemoryConnectorProfileRepository
from rag.repositories.folder_schedule_memory import InMemoryFolderScheduleRepository
from rag.retrieval.service import RetrievalService
from rag.schemas.query import QueryRequest


@dataclass
class FakeConfig:
    connector_live_sql_enabled: bool = True
    connector_live_sql_max_rows: int = 2
    connector_live_sql_timeout_seconds: int = 15
    connector_live_sql_max_scopes: int = 5
    connector_live_sql_max_schedules: int = 5
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

    def generate_json(self, *, prompt: str, model: str | None, system: str, cancellation_token=None) -> str:
        _ = model, system, cancellation_token
        self.generated_prompts.append(prompt)
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
        _ = model, system, cancellation_token
        self.generated_prompts.append(prompt)
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

    sources = sources_from_hits(result.hits, query=ctx["request"].query)
    assert sources[0].doc_title == "Live connector query: Fake cases approved database scope"
    assert sources[0].excerpt


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


def test_retrieval_service_prepends_live_sql_for_structured_and_explicit_database_routes() -> None:
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
    structured_ctx = _ctx("List all live case statuses")
    structured_hits = service.retrieve(structured_ctx)

    assert structured_hits[0].payload["source_type"] == "connector_live_sql_database_scope"
    assert structured_hits[1].payload["doc_id"] == "indexed"
    assert structured_ctx["execution_modes"]["live_sql_retriever"] == "ai_assisted"
    assert len(llm.generated_prompts) == 1

    factual_ctx = _ctx("What is the indexed fallback?", structured=False)
    factual_hits = service.retrieve(factual_ctx)

    assert [hit.payload["doc_id"] for hit in factual_hits] == ["indexed"]
    assert factual_ctx["execution_modes"]["live_sql_retriever"] == "skipped"
    assert len(llm.generated_prompts) == 1

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
    assert len(llm.generated_prompts) == 2


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
    ctx = _ctx("What is the status?", structured=False)
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


def _ctx(query: str, *, group_paths: tuple[str, ...] = ("/ops",), structured: bool = True):
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
        public_intent="aggregation" if structured else "factual_simple",
        use_structured_query=structured,
        search_mode="structured_first" if structured else "hybrid",
        top_k=10,
    )
    return ctx
