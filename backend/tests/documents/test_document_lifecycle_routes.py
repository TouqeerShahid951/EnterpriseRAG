from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from rag.documents import routes as document_routes
from rag.documents.adapters.memory import InMemoryDocumentRepository

from document_route_characterization_support import (
    FakeGraphQueue,
    FakeGraphRAG,
    FakeIngestQueue,
    FakeQdrant,
    FakeStorage,
    _csrf_request,
    _document,
    _lifecycle_service,
    _user,
)


def test_soft_delete_removes_indexes_marks_deleted_and_audits_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(document_routes.settings, "graphrag_enabled", True)
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    qdrant = FakeQdrant()
    graphrag = FakeGraphRAG()
    graph_queue = FakeGraphQueue()

    response = asyncio.run(
        document_routes.delete_document(
            document.id,
            _csrf_request("DELETE"),
            user=user,
            service=_lifecycle_service(
                repo,
                qdrant=qdrant,
                graphrag=graphrag,
                graph_queue=graph_queue,
            ),
        )
    )

    assert response.status == "soft_deleted"
    assert repo.get_document(document.id, include_deleted=True).deleted_at is not None  # type: ignore[union-attr]
    assert qdrant.deleted_documents == [document.id]
    assert len(graph_queue.partition_messages) == 1
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_soft_delete_vector_failure_leaves_document_active_and_audits_failure() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    graphrag = FakeGraphRAG()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.delete_document(
                document.id,
                _csrf_request("DELETE"),
                user=user,
                service=_lifecycle_service(
                    repo,
                    qdrant=FakeQdrant(fail_delete=True),
                    graphrag=graphrag,
                ),
            )
        )

    assert exc_info.value.status_code == 502
    assert repo.get_document(document.id) is not None
    assert len(graphrag.deleted) == 1
    assert repo.audit_events[-1]["payload"]["error_code"] == "document_vectors_delete_failed"


def test_restore_queue_failure_leaves_document_restored_and_failed_job_recorded() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    repo.soft_delete_document(document.id)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.restore_document(
                document.id,
                _csrf_request("POST"),
                user=user,
                service=_lifecycle_service(
                    repo,
                    ingest_queue=FakeIngestQueue(error="redis unavailable"),
                ),
            )
        )

    current = repo.get_document(document.id, include_deleted=True)
    jobs = repo.list_ingest_jobs()
    assert exc_info.value.status_code == 503
    assert current is not None and current.deleted_at is None
    assert len(jobs) == 1 and jobs[0].status == "failed"
    assert repo.audit_events[-1]["event_type"] == "documents.restore"


def test_permanent_delete_rejects_contributor_before_external_cleanup() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    qdrant = FakeQdrant()
    graphrag = FakeGraphRAG()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.permanently_delete_document(
                document.id,
                _csrf_request("DELETE"),
                user=user,
                service=_lifecycle_service(
                    repo,
                    qdrant=qdrant,
                    graphrag=graphrag,
                ),
            )
        )

    assert exc_info.value.status_code == 403
    assert qdrant.deleted_documents == []
    assert graphrag.deleted == []


def test_permanent_delete_storage_failure_preserves_database_record() -> None:
    repo = InMemoryDocumentRepository()
    admin = _user("platform_admin")
    document = _document(repo, user=admin)
    qdrant = FakeQdrant()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.permanently_delete_document(
                document.id,
                _csrf_request("DELETE"),
                user=admin,
                service=_lifecycle_service(
                    repo,
                    storage=FakeStorage(
                        delete_error="object store unavailable"
                    ),
                    qdrant=qdrant,
                ),
            )
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "document_file_delete_failed"
    assert qdrant.deleted_documents == [document.id]
    assert repo.get_document(document.id, include_deleted=True) is not None
