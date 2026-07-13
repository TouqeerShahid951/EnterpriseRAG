from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rag.connectors.crypto import decrypt_secret, encrypt_secret, keyring_from_settings, redact_secrets
from rag.connectors.models import CONNECTOR_RECORD_CONTENT_TYPE
from rag.connectors.registry import (
    PostgresConnector,
    SqlServerConnector,
    UnsupportedConnector,
    _add_foreign_key_rows,
    _add_index_rows,
    _add_primary_key_rows,
    _add_sample_estimate_rows,
    _finalize_tables,
    _postgres_connection_kwargs,
    _quote_postgres_ident,
    _tables_from_column_rows,
    default_connector_registry,
)
from rag.connectors.schema_enrichment import (
    enrich_schema_table_with_llm,
    initialize_schema_catalog_enrichment,
    schema_catalog_with_table_enrichment_failure,
)
from rag.connectors.sql_safety import (
    SqlValidationError,
    validate_live_sql_for_approved_catalog,
    validate_read_only_sql,
)
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.ingestion.folders.adapters.memory import InMemoryFolderScheduleRepository
from rag.ingestion.folders.adapters.sources import LocalFileSystemSource
from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.ingestion.folders.config import FolderIngestionConfig
from rag.ingestion.folders.dispatch import dispatch_due_schedules
from rag.ingestion.folders.service import create_local_folder_schedule
from rag.ingestion.folders.sources import list_local_folder_directories
from rag.ingestion.queue import InMemoryIngestQueue
from rag.documents.storage import StoredUpload
from rag.ingestion.parsers.document import parse_document


FOLDER_CONFIG = FolderIngestionConfig(
    default_timezone="Asia/Karachi",
    sources_root="/folder-sources",
    snapshot_max_files=100,
    snapshot_max_bytes=5 * 1024 * 1024 * 1024,
    upload_max_bytes=50 * 1024 * 1024,
)


class FakeMinioSource:
    def list_objects(self, **kwargs):
        return []


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, filename: str, content: bytes, content_type: str | None) -> StoredUpload:
        object_path = f"memory://{len(self.objects)}-{filename}"
        self.objects[object_path] = content
        return StoredUpload(object_path=object_path, size_bytes=len(content), content_type=content_type)


class FakeSchemaEnrichmentLlm:
    def __init__(self, response: str | list[str]) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def generate_json(self, **kwargs) -> str:
        self.requests.append(dict(kwargs))
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def test_secret_envelope_round_trips_and_redacts() -> None:
    keys = keyring_from_settings("unit-test-key")
    encrypted = encrypt_secret({"username": "readonly", "password": "secret"}, keys)

    assert "secret" not in encrypted
    assert decrypt_secret(encrypted, keys) == {"username": "readonly", "password": "secret"}
    assert redact_secrets({"username": "readonly", "password": "secret"}) == {"username": "********", "password": "********"}


def test_sql_server_validation_blocks_unsafe_statements() -> None:
    assert validate_read_only_sql("WITH rows AS (SELECT id FROM dbo.Cases) SELECT * FROM rows;") == "WITH rows AS (SELECT id FROM dbo.Cases) SELECT * FROM rows"

    for query in [
        "UPDATE dbo.Cases SET status = 'x'",
        "SELECT * INTO dbo.Copy FROM dbo.Cases",
        "SELECT * FROM dbo.Cases; DROP TABLE dbo.Cases",
        "EXEC xp_cmdshell 'dir'",
        "SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'SELECT 1')",
        "SELECT * FROM dbo.Cases -- hidden",
    ]:
        with pytest.raises(SqlValidationError):
            validate_read_only_sql(query, connector_type="sql_server")


def test_postgres_validation_blocks_unsafe_statements() -> None:
    assert validate_read_only_sql("SELECT id, status FROM public.cases", connector_type="postgres") == "SELECT id, status FROM public.cases"

    for query in [
        "CALL refresh_case_cache()",
        "COPY public.cases TO PROGRAM 'cat'",
        "SELECT * INTO public.case_copy FROM public.cases",
        "SELECT * FROM public.cases FOR UPDATE",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity",
    ]:
        with pytest.raises(SqlValidationError):
            validate_read_only_sql(query, connector_type="postgres")


def test_live_sql_validation_allows_only_approved_catalog_scope() -> None:
    catalog = {
        "tables": [
            {
                "key": "public.cases",
                "schema": "public",
                "name": "cases",
                "allowed": True,
                "sensitive": False,
                "columns": [
                    {"name": "id", "allowed": True, "sensitive": False},
                    {"name": "status", "allowed": True, "sensitive": False},
                    {"name": "person_id", "allowed": True, "sensitive": False},
                    {"name": "secret_note", "allowed": False, "sensitive": True},
                ],
            },
            {
                "key": "public.people",
                "schema": "public",
                "name": "people",
                "allowed": True,
                "sensitive": False,
                "columns": [
                    {"name": "id", "allowed": True, "sensitive": False},
                    {"name": "name", "allowed": True, "sensitive": False},
                ],
            },
        ],
        "relationships": [
            {
                "left_table": "public.cases",
                "left_columns": ["person_id"],
                "right_table": "public.people",
                "right_columns": ["id"],
                "allowed": True,
            }
        ],
    }

    validated = validate_live_sql_for_approved_catalog(
        "SELECT c.status, COUNT(*) AS total FROM public.cases c GROUP BY c.status",
        catalog_json=catalog,
        connector_type="postgres",
        row_limit=10,
    )
    assert "LIMIT 10" in validated

    joined = validate_live_sql_for_approved_catalog(
        "SELECT c.status, p.name FROM public.cases c JOIN public.people p ON p.id = c.person_id LIMIT 5",
        catalog_json=catalog,
        connector_type="postgres",
        row_limit=10,
    )
    assert joined.endswith("LIMIT 5")

    for query in [
        "SELECT * FROM public.cases",
        "SELECT secret_note FROM public.cases",
        "SELECT status FROM public.incidents",
        "SELECT c.status, p.name FROM public.cases c JOIN public.people p ON p.name = c.status",
        "SELECT c.status, p.name FROM public.cases c, public.people p",
        "WITH leaked AS (SELECT status FROM public.cases) SELECT * FROM leaked",
        "SELECT status FROM public.cases; SELECT name FROM public.people",
        "DELETE FROM public.cases",
    ]:
        with pytest.raises(SqlValidationError):
            validate_live_sql_for_approved_catalog(query, catalog_json=catalog, connector_type="postgres", row_limit=10)

    with pytest.raises(SqlValidationError) as excinfo:
        validate_live_sql_for_approved_catalog(
            "SELECT c.missing_id FROM public.cases c LIMIT 5",
            catalog_json=catalog,
            connector_type="postgres",
            row_limit=10,
        )
    message = str(excinfo.value)
    assert "c.missing_id" in message
    assert "public.cases" in message
    assert "status" in message


def test_connector_registry_exposes_sql_server_and_postgres() -> None:
    registry = default_connector_registry()

    assert isinstance(registry.get("sql_server"), SqlServerConnector)
    assert isinstance(registry.get("postgres"), PostgresConnector)
    assert isinstance(registry.get("mysql"), UnsupportedConnector)


def test_postgres_connection_kwargs_use_public_config_and_encrypted_secrets() -> None:
    kwargs = _postgres_connection_kwargs(
        {"host": "postgres.internal", "port": "5433", "database": "cases", "sslmode": "require", "connect_timeout_seconds": 7},
        {"username": "readonly", "password": "secret"},
    )

    assert kwargs == {
        "host": "postgres.internal",
        "port": 5433,
        "dbname": "cases",
        "user": "readonly",
        "password": "secret",
        "connect_timeout": 7,
        "sslmode": "require",
    }


def test_connector_introspection_helpers_shape_relational_metadata() -> None:
    tables = _tables_from_column_rows(
        "postgres",
        [
            {
                "table_schema": "public",
                "table_name": "cases",
                "table_type": "BASE TABLE",
                "column_name": "id",
                "ordinal_position": 1,
                "data_type": "uuid",
                "is_nullable": "NO",
                "character_maximum_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
            },
            {
                "table_schema": "public",
                "table_name": "cases",
                "table_type": "BASE TABLE",
                "column_name": "person_id",
                "ordinal_position": 2,
                "data_type": "uuid",
                "is_nullable": "NO",
                "character_maximum_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
            },
            {
                "table_schema": "public",
                "table_name": "people",
                "table_type": "BASE TABLE",
                "column_name": "id",
                "ordinal_position": 1,
                "data_type": "uuid",
                "is_nullable": "NO",
                "character_maximum_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
            },
        ],
    )
    _add_primary_key_rows(tables, [{"table_schema": "public", "table_name": "cases", "constraint_name": "cases_pkey", "column_name": "id"}])
    _add_foreign_key_rows(
        tables,
        [
            {
                "table_schema": "public",
                "table_name": "cases",
                "constraint_name": "cases_person_id_fkey",
                "column_name": "person_id",
                "referenced_table_schema": "public",
                "referenced_table_name": "people",
                "referenced_column_name": "id",
            }
        ],
    )
    _add_index_rows(tables, [{"table_schema": "public", "table_name": "cases", "index_name": "cases_person_idx", "is_unique": False, "index_type": "btree", "column_name": "person_id"}])
    _add_sample_estimate_rows(tables, [{"table_schema": "public", "table_name": "cases", "estimated_row_count": 25}])

    finalized = _finalize_tables(tables)
    cases = next(table for table in finalized if table["name"] == "cases")

    assert cases["connector_type"] == "postgres"
    assert cases["primary_keys"] == [{"name": "cases_pkey", "columns": ["id"]}]
    assert cases["foreign_keys"] == [
        {
            "name": "cases_person_id_fkey",
            "columns": ["person_id"],
            "referenced_table": "public.people",
            "referenced_columns": ["id"],
        }
    ]
    assert cases["indexes"] == [{"name": "cases_person_idx", "columns": ["person_id"], "unique": False, "type": "btree"}]
    assert cases["sample_metadata"]["estimated_row_count"] == 25
    assert _quote_postgres_ident('case"records') == '"case""records"'


def test_schema_table_enrichment_checkpoints_each_table_without_changing_scope() -> None:
    catalog = initialize_schema_catalog_enrichment(
        {
            "tables": [
                {
                    "key": "public.cases",
                    "allowed": True,
                    "sensitive": False,
                    "description": "",
                    "columns": [
                        {"name": "id", "data_type": "integer", "allowed": True, "sensitive": False, "description": ""},
                        {"name": "secret_note", "data_type": "text", "allowed": False, "sensitive": True, "description": ""},
                    ],
                },
                {
                    "key": "public.people",
                    "allowed": True,
                    "sensitive": False,
                    "description": "",
                    "columns": [{"name": "id", "data_type": "integer", "allowed": True, "sensitive": False, "description": ""}],
                },
            ],
            "relationships": [],
        }
    )
    llm = FakeSchemaEnrichmentLlm(
        '{"tables":[{"key":"public.cases","description":"Operational case records.",'
        '"columns":[{"name":"id","description":"Stable case identifier."},'
        '{"name":"secret_note","description":"Restricted case note."}]}],"business_rules":[]}'
    )

    enriched = enrich_schema_table_with_llm(
        catalog,
        table_key="public.cases",
        connector_type="postgres",
        profile_name="Cases",
        llm=llm,
        model=None,
    )

    assert enriched["tables"][0]["description"] == "Operational case records."
    assert enriched["tables"][0]["columns"][1]["allowed"] is False
    assert enriched["tables"][0]["columns"][1]["sensitive"] is True
    assert enriched["tables"][1]["description"] == ""
    assert enriched["ai_enrichment"]["status"] == "in_progress"
    assert enriched["ai_enrichment"]["completed_tables"] == 1
    assert enriched["ai_enrichment"]["total_tables"] == 2
    assert "public.people" not in str(llm.requests[0]["prompt"])
    assert "secret_note" in str(llm.requests[0]["prompt"])


def test_schema_table_enrichment_failure_is_checkpointed_and_retryable() -> None:
    catalog = initialize_schema_catalog_enrichment(
        {"tables": [{"key": "public.cases", "description": "", "columns": []}], "relationships": []}
    )
    failed = schema_catalog_with_table_enrichment_failure(catalog, table_key="public.cases", error_message="model timeout")

    assert failed["ai_enrichment"]["status"] == "partial"
    assert failed["ai_enrichment"]["failed_tables"] == 1
    assert failed["ai_enrichment"]["table_statuses"][0]["error_message"] == "model timeout"

    retried = enrich_schema_table_with_llm(
        failed,
        table_key="public.cases",
        connector_type="postgres",
        profile_name="Cases",
        llm=FakeSchemaEnrichmentLlm('{"tables":[{"key":"public.cases","description":"Case records."}]}'),
        model=None,
    )

    assert retried["ai_enrichment"]["status"] == "generated"
    assert retried["ai_enrichment"]["failed_tables"] == 0


def test_schema_table_enrichment_requires_descriptions_for_every_column() -> None:
    catalog = initialize_schema_catalog_enrichment(
        {
            "tables": [
                {
                    "key": "public.cases",
                    "description": "",
                    "columns": [
                        {"name": "id", "description": ""},
                        {"name": "status", "description": ""},
                    ],
                }
            ],
            "relationships": [],
        }
    )
    llm = FakeSchemaEnrichmentLlm(
        '{"tables":[{"key":"public.cases","description":"Case records.",'
        '"columns":[{"name":"id","description":"Stable case identifier."}]}]}'
    )

    enriched = enrich_schema_table_with_llm(
        catalog,
        table_key="public.cases",
        connector_type="postgres",
        profile_name="Cases",
        llm=llm,
        model=None,
    )

    assert llm.calls == 2
    assert enriched["tables"][0]["columns"][0]["description"] == "Stable case identifier."
    assert enriched["tables"][0]["columns"][1]["description"] == ""
    assert enriched["ai_enrichment"]["status"] == "partial"
    assert enriched["ai_enrichment"]["failed_tables"] == 1


def test_connector_record_parser_uses_direct_chunk_shape() -> None:
    parsed = parse_document(
        b'{"title":"FIR row","identity":{"id":123},"data":{"fir_number":"FIR-2024-88","status":"Open"}}',
        content_type=CONNECTOR_RECORD_CONTENT_TYPE,
        file_path="memory://record.connector.json",
        min_chars_per_page=10,
    )

    assert parsed.provenance["document_kind"] == "connector_record"
    assert parsed.provenance["routing_mode"] == "direct_chunks"
    assert parsed.items[0].parser == "connector_record"
    assert "FIR-2024-88" in parsed.items[0].text


def test_dispatch_cancels_legacy_connector_schedules_without_syncing() -> None:
    _identity_repo, user = _identity()
    document_repo = InMemoryDocumentRepository()
    schedule_repo = InMemoryFolderScheduleRepository()
    queue = InMemoryIngestQueue()
    now = datetime.now(UTC)
    schedule = schedule_repo.create_schedule(
        name="Legacy connector sync",
        source_type="connector",
        schedule_type="recurring",
        status="active",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="case record",
        effective_date=None,
        expiry_date=None,
        description=None,
        timezone="Asia/Karachi",
        scheduled_at=None,
        recurrence={"days_of_week": [0, 1, 2, 3, 4, 5, 6], "start_time": "00:00", "end_time": "23:59"},
        source_config={"connector_profile_id": "profile-1", "connector_type": "fake"},
        created_by=user.id,
        next_run_at=now,
    )

    dispatched = dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=FakeMinioSource(),
        config=FOLDER_CONFIG,
        now=now,
    )

    assert dispatched == []
    assert queue.messages == []
    assert schedule_repo.list_runs(schedule.id) == []
    assert schedule_repo.get_schedule(schedule.id).status == "cancelled"


def test_local_folder_watcher_syncs_new_and_changed_files(tmp_path) -> None:
    watch_root = tmp_path / "watch"
    watch_root.mkdir()
    source_file = watch_root / "case.json"
    source_file.write_text('{"id":"1","status":"open"}', encoding="utf-8")
    (watch_root / "notes.txt").write_text("unsupported", encoding="utf-8")

    identity_repo, user = _identity()
    document_repo = InMemoryDocumentRepository()
    schedule_repo = InMemoryFolderScheduleRepository()
    queue = InMemoryIngestQueue()
    storage = MemoryStorage()
    local_source = LocalFileSystemSource()
    schedule = create_local_folder_schedule(
        name="Case folder watcher",
        path=str(watch_root),
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        effective_date=None,
        expiry_date=None,
        doc_type="case record",
        description=None,
        schedule_type="recurring",
        timezone_name="Asia/Karachi",
        scheduled_at=None,
        recurrence={"days_of_week": [0, 1, 2, 3, 4, 5, 6], "start_time": "00:00", "end_time": "23:59"},
        user=user,
        identity_repo=identity_repo,
        document_repo=document_repo,
        schedule_repo=schedule_repo,
        local_folder_source=local_source,
        config=FOLDER_CONFIG,
    )

    now = datetime.now(UTC)
    dispatched = dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=FakeMinioSource(),
        local_folder_source=local_source,
        storage=storage,
        config=FOLDER_CONFIG,
        now=now,
    )

    assert dispatched == [schedule.id]
    assert len(queue.messages) == 1
    assert len(storage.objects) == 1
    assert {item.skip_code for run in schedule_repo.list_runs(schedule.id) for item in schedule_repo.list_run_items(run.id)} >= {"unsupported_file_type"}

    schedule_repo.update_schedule_next_run(schedule.id, status="active", next_run_at=now)
    dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=FakeMinioSource(),
        local_folder_source=local_source,
        storage=storage,
        config=FOLDER_CONFIG,
        now=now,
    )

    assert len(queue.messages) == 1
    assert any(item.skip_code == "unchanged_source" for run in schedule_repo.list_runs(schedule.id) for item in schedule_repo.list_run_items(run.id))

    source_file.write_text('{"id":"1","status":"closed"}', encoding="utf-8")
    schedule_repo.update_schedule_next_run(schedule.id, status="active", next_run_at=now)
    dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=FakeMinioSource(),
        local_folder_source=local_source,
        storage=storage,
        config=FOLDER_CONFIG,
        now=now,
    )

    assert len(queue.messages) == 2
    assert queue.messages[-1].supersedes
    assert len(document_repo.list_documents()) == 2


def test_local_folder_browser_lists_directories_under_root(tmp_path) -> None:
    root = tmp_path / "folder-sources"
    cases = root / "cases"
    nested = cases / "incoming"
    empty = root / "empty"
    nested.mkdir(parents=True)
    empty.mkdir(parents=True)
    (root / "case.json").write_text("{}", encoding="utf-8")

    source = LocalFileSystemSource()
    browse_root, current, parent, items = list_local_folder_directories(
        source=source,
        root_path=str(root),
    )

    assert browse_root == root.resolve()
    assert current == root.resolve()
    assert parent is None
    assert [(item.name, item.has_children) for item in items] == [("cases", True), ("empty", False)]

    _, current, parent, items = list_local_folder_directories(
        source=source,
        root_path=str(root),
        current_path=str(cases),
    )

    assert current == cases.resolve()
    assert parent == root.resolve()
    assert [item.name for item in items] == ["incoming"]

    with pytest.raises(RuntimeError):
        list_local_folder_directories(
            source=source,
            root_path=str(root),
            current_path=str(tmp_path),
        )


def _identity():
    repo = InMemoryIdentityRepository()
    repo.create_group(path="/ops", name="Ops")
    user = repo.create_user(
        email="space-admin@example.test",
        name="Space Admin",
        password_hash="hash",
        group_paths=["/ops"],
        is_active=True,
        account_type="space_admin",
        clearance_level="NATO_RESTRICTED",
    )
    return repo, user
