from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE
from rag.ingestion import maintenance
from rag.ingestion.adapters import backend as backend_adapter
from rag.ingestion.adapters.backend import BackendInternalClient
from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.chunking import TextChunk
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.indexing import qdrant as indexing_qdrant
from rag.ingestion.indexing.payloads import build_qdrant_points
from rag.ingestion.indexing.qdrant import QdrantClient
from rag.ingestion.indexing.sparse import SparseVector
from rag.ingestion.pipeline.indexing_stages import upsert_qdrant
from rag.ingestion.publication.adapters import postgres as publication_postgres
from rag.ingestion.publication.models import (
    IndexGeneration,
    aggregate_generation_hash,
)
from rag.ingestion.publication.schema import (
    INGEST_PUBLICATION_SCHEMA_SQL,
    INGEST_PUBLICATION_SCHEMA_VERSION,
    ensure_ingest_publication_schema,
)


def test_generation_points_are_isolated_and_hidden_until_publication() -> None:
    points = build_qdrant_points(
        job=_job(),
        chunks=[_chunk()],
        vectors=[[0.1, 0.2]],
        sparse_vectors=[SparseVector(indices=[], values=[])],
        metadata={},
        file_bytes=b"document",
        index_generation_id="generation-a",
    )
    retry_points = build_qdrant_points(
        job=_job(),
        chunks=[_chunk()],
        vectors=[[0.1, 0.2]],
        sparse_vectors=[SparseVector(indices=[], values=[])],
        metadata={},
        file_bytes=b"document",
        index_generation_id="generation-b",
    )

    payload = points[0]["payload"]
    assert points[0]["id"] != retry_points[0]["id"]
    assert payload["index_generation_id"] == "generation-a"
    assert payload["generation_published"] is False
    assert payload["is_current"] is False


def test_declared_glossary_type_survives_generated_metadata() -> None:
    points = build_qdrant_points(
        job=IngestJobPayload(
            job_id="job-glossary",
            doc_id="document-glossary",
            file_path="memory://glossary.pdf",
            group_path="/ops",
            effective_date=None,
            supersedes=[],
            doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
        ),
        chunks=[_chunk()],
        vectors=[[0.1, 0.2]],
        sparse_vectors=[SparseVector(indices=[], values=[])],
        metadata={"doc_type": "policy"},
        file_bytes=b"glossary",
    )

    assert points[0]["payload"]["doc_type"] == ABBREVIATION_GLOSSARY_DOC_TYPE


def test_qdrant_stages_verifies_and_publishes_only_one_generation(
    monkeypatch,
) -> None:
    requests: list[tuple[str, dict[str, Any]]] = []
    point = {
        "id": "point-a",
        "vector": {"dense": [0.1, 0.2]},
        "payload": {
            "doc_id": "doc-a",
            "index_generation_id": "generation-a",
            "generation_item_hash": "item-a",
        },
    }

    def request_json(_base_url: str, path: str, **kwargs: Any) -> dict[str, Any]:
        requests.append((path, kwargs))
        if path.endswith("/scroll"):
            return {"result": {"points": [point], "next_page_offset": None}}
        return {"result": {}}

    monkeypatch.setattr(indexing_qdrant, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=1,
    )
    client._vector_size = 2  # noqa: SLF001 - avoids collection setup in adapter test

    assert client.stage_generation(generation_id="generation-a", points=[point]) == 1
    client.verify_generation(
        generation_id="generation-a",
        expected_point_count=1,
        expected_item_hash=aggregate_generation_hash(["item-a"]),
        vector_dimension=2,
    )
    client.publish_generation("generation-a")

    delete_path, delete_request = requests[0]
    assert delete_path.endswith("/points/delete?wait=true")
    assert delete_request["payload"] == {
        "filter": {
            "must": [
                {"key": "index_generation_id", "match": {"value": "generation-a"}}
            ]
        }
    }
    publish_path, publish_request = requests[-1]
    assert publish_path.endswith("/points/payload?wait=true")
    assert publish_request["payload"]["payload"] == {
        "generation_published": True,
        "is_current": True,
    }


def test_pipeline_verifies_before_publishing_and_activating() -> None:
    calls: list[str] = []

    class Backend:
        def update_job(self, **_kwargs: Any) -> None:
            calls.append("progress")

        def verify_index_generation(self, **_kwargs: Any) -> None:
            calls.append("verified")

    class Index:
        def ensure_collection(self, _dimension: int) -> None:
            calls.append("ensure")

        def stage_generation(self, **kwargs: Any) -> int:
            calls.append("stage")
            kwargs["guard"]()
            return len(kwargs["points"])

        def verify_generation(self, **_kwargs: Any) -> None:
            calls.append("qdrant_verified")

        def publish_generation(self, _generation_id: str, **kwargs: Any) -> None:
            calls.append("publish")
            kwargs["guard"]()

    state = {
        "payload": _job(),
        "vectors": [[0.1, 0.2]],
        "index_generation_id": "generation-a",
        "points": [
            {
                "id": "point-a",
                "payload": {"generation_item_hash": "item-a"},
            }
        ],
    }

    result = upsert_qdrant(state, type("Dependencies", (), {"backend": Backend(), "qdrant": Index()})())  # type: ignore[arg-type]

    assert result["upsert_count"] == 1
    assert calls == [
        "ensure",
        "progress",
        "stage",
        "qdrant_verified",
        "verified",
        "publish",
        "progress",
    ]


def test_publication_conflict_preserves_the_worker_lease(monkeypatch) -> None:
    client = BackendInternalClient(
        base_url="http://backend.test",
        service_token="test-token",
        timeout_seconds=1,
    )
    client._bind_run_token("job-a", "run-a")  # noqa: SLF001 - assert client lease state

    def request_json(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ServiceRequestError(
            "backend",
            '{"detail":{"code":"index_generation_conflict"}}',
            409,
        )

    monkeypatch.setattr(backend_adapter, "request_json", request_json)

    with pytest.raises(ServiceRequestError):
        client.verify_index_generation(job_id="job-a", generation_id="generation-a")

    client.ensure_lease("job-a")
    with pytest.raises(ServiceRequestError):
        client.verify_index_generation(job_id="job-a", generation_id="generation-a")


def test_activation_commits_the_pointer_and_job_in_one_transaction(monkeypatch) -> None:
    connection = _ActivationConnection()
    repository = publication_postgres.PostgresIndexPublicationRepository("postgresql://test")
    monkeypatch.setattr(repository, "_connect", lambda: connection)
    staged: list[dict[str, object]] = []
    glossary: list[dict[str, object]] = []

    def apply_staged_ingestion_data(conn: object, **kwargs: object) -> None:
        staged.append({"conn": conn, **kwargs})

    monkeypatch.setattr(
        publication_postgres,
        "apply_staged_ingestion_data",
        apply_staged_ingestion_data,
    )

    def replace_abbreviation_glossary(conn: object, **kwargs: object) -> None:
        glossary.append({"conn": conn, **kwargs})

    monkeypatch.setattr(
        publication_postgres,
        "replace_abbreviation_glossary_in_transaction",
        replace_abbreviation_glossary,
    )

    generation = repository.activate(
        generation_id="generation-a",
        job_id="job-a",
        run_token="run-a",
    )

    assert generation.state == "active"
    assert connection.transaction_count == 1
    assert staged == [
        {
            "conn": connection,
            "document_id": "document-a",
            "metadata": {"summary": "Updated"},
            "claims": [],
            "supersedes": [],
        }
    ]
    assert glossary == [
        {
            "conn": connection,
            "document_id": "document-a",
            "entries": [("AD", "Assistant Director", 7)],
        }
    ]
    assert connection.statement_params("SET state = 'retiring'") == (
        "document-a",
        "generation-a",
    )
    assert connection.statement_params("SET active_index_generation_id = %s") == (
        "generation-a",
        "document-a",
    )
    assert connection.statement_params("SET status = 'complete'") == (
        "[]",
        "job-a",
        "run-a",
    )


def test_retirement_deletes_only_retiring_generations() -> None:
    generation = IndexGeneration(
        id="generation-a",
        document_id="document-a",
        job_id="job-a",
        state="retiring",
        expected_point_count=1,
        expected_item_hash="a" * 64,
        vector_dimension=2,
    )

    class Publication:
        def __init__(self) -> None:
            self.retired: list[str] = []

        def list_retiring(self, *, limit: int) -> tuple[IndexGeneration, ...]:
            assert limit == 20
            return (generation,)

        def mark_retired(self, generation_id: str) -> bool:
            self.retired.append(generation_id)
            return True

    class Index:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_generation_points(self, generation_id: str) -> None:
            self.deleted.append(generation_id)

    publication = Publication()
    index = Index()

    assert maintenance.retire_index_generations(publication=publication, qdrant=index) == 1  # type: ignore[arg-type]
    assert index.deleted == ["generation-a"]
    assert publication.retired == ["generation-a"]


def test_publication_migration_runs_once() -> None:
    connection = _RecordingConnection()

    assert ensure_ingest_publication_schema(connection) is True
    assert ensure_ingest_publication_schema(connection) is False
    assert connection.statements.count(INGEST_PUBLICATION_SCHEMA_SQL) == 1
    assert connection.reserved_versions == {INGEST_PUBLICATION_SCHEMA_VERSION}
    assert "document_index_generations" in INGEST_PUBLICATION_SCHEMA_SQL
    assert "active_index_generation_id" in INGEST_PUBLICATION_SCHEMA_SQL


class _Result:
    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.reserved_versions: set[int] = set()

    def execute(
        self,
        statement: str,
        params: tuple[Any, ...] = (),
    ) -> _Result:
        self.statements.append(statement)
        if "INSERT INTO ingest_publication_schema_migrations" not in statement:
            return _Result()
        version = int(params[0])
        if version in self.reserved_versions:
            return _Result()
        self.reserved_versions.add(version)
        return _Result({"version": version})

    @contextmanager
    def transaction(self):
        yield


class _ActivationConnection:
    def __init__(self) -> None:
        self.transaction_count = 0
        self._in_transaction = False
        self._statements: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> _ActivationConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @contextmanager
    def transaction(self):
        assert not self._in_transaction
        self.transaction_count += 1
        self._in_transaction = True
        try:
            yield
        finally:
            self._in_transaction = False

    def execute(
        self,
        statement: str,
        params: tuple[Any, ...] = (),
    ) -> _Result:
        assert self._in_transaction
        normalized = " ".join(statement.split())
        self._statements.append((normalized, params))
        if normalized.startswith("SELECT id, doc_id, status, run_token"):
            return _Result(
                {
                    "id": "job-a",
                    "doc_id": "document-a",
                    "status": "processing",
                    "run_token": "run-a",
                }
            )
        if normalized.startswith("SELECT * FROM document_index_generations"):
            return _Result(
                {
                    "id": "generation-a",
                    "document_id": "document-a",
                    "job_id": "job-a",
                    "state": "verified",
                    "expected_point_count": 1,
                    "expected_item_hash": "a" * 64,
                    "vector_dimension": 2,
                    "staged_metadata": {
                        "metadata": {"summary": "Updated"},
                        "claims": [],
                        "supersedes": [],
                        "warnings": [],
                        "abbreviation_entries": [
                            {
                                "abbreviation": "AD",
                                "expansion": "Assistant Director",
                                "source_page": 7,
                            }
                        ],
                    },
                }
            )
        if normalized.startswith(
            "SELECT id, active_index_generation_id FROM documents"
        ):
            return _Result({"id": "document-a", "active_index_generation_id": "old"})
        if "SET state = 'active'" in normalized:
            return _Result(
                {
                    "id": "generation-a",
                    "document_id": "document-a",
                    "job_id": "job-a",
                    "state": "active",
                    "expected_point_count": 1,
                    "expected_item_hash": "a" * 64,
                    "vector_dimension": 2,
                }
            )
        if "SET status = 'complete'" in normalized:
            return _Result({"id": "job-a"})
        return _Result()

    def statement_params(self, fragment: str) -> tuple[Any, ...]:
        for statement, params in self._statements:
            if fragment in statement:
                return params
        raise AssertionError(f"statement containing {fragment!r} was not executed")


def _job() -> IngestJobPayload:
    return IngestJobPayload(
        job_id="job-a",
        doc_id="document-a",
        file_path="memory://document.pdf",
        group_path="/ops",
        effective_date=None,
        supersedes=[],
    )


def _chunk() -> TextChunk:
    return TextChunk(
        index=0,
        page=1,
        text="Document text",
        parent_chunk_id="document-a:parent:0",
        parent_text="Document text",
        chunk_type="text",
        section_title=None,
        page_start=1,
        page_end=1,
    )
