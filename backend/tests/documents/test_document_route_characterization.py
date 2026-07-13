from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from rag.documents import routes as document_routes
from rag.auth.identity_models import UserRecord
from rag.core.config import settings
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.adapters.metadata_index import QdrantDocumentMetadataIndex
from rag.documents.adapters.access_scope_graph import GraphRAGDocumentStore
from rag.documents.adapters.lifecycle import (
    GraphRAGPartitionRebuildQueue,
    QdrantDocumentVectorIndex,
)
from rag.documents.lifecycle_service import DocumentLifecycleService
from rag.documents.metadata_service import DocumentMetadataService
from rag.documents.reingestion_service import DocumentReingestionService
from rag.documents.storage import StoredUploadContent
from rag.graphrag.cleanup import GraphRAGCleanupResult
from rag.graphrag import document_routes as graphrag_document_routes
from rag.ingestion import document_routes as ingestion_document_routes
from rag.graphrag.adapters.document_enrichment_queue import (
    GraphRAGDocumentEnrichmentQueue,
)
from rag.graphrag.document_enrichment_service import (
    DocumentGraphEnrichmentService,
)
from rag.ingestion.contracts import IngestJobPayload
from rag.query.http import ServiceRequestError
from rag.schemas.docs import DocumentClearanceUpdateRequest, DocumentTopicsUpdateRequest
from rag.graphrag.maintenance_queue import (
    GraphRAGDocumentIndexMessage,
    GraphRAGPartitionRebuildMessage,
)


class FakeQdrant:
    def __init__(self, *, fail_clearance: bool = False, fail_topics: bool = False, fail_delete: bool = False) -> None:
        self.fail_clearance = fail_clearance
        self.fail_topics = fail_topics
        self.fail_delete = fail_delete
        self.collection = settings.qdrant_collection
        self.clearance_updates: list[tuple[str, str, int]] = []
        self.topic_updates: list[tuple[str, list[str], list[str]]] = []
        self.deleted_documents: list[str] = []

    def set_document_clearance(
        self,
        doc_id: str,
        *,
        clearance_level: str,
        clearance_rank: int,
    ) -> None:
        if self.fail_clearance:
            raise ServiceRequestError("qdrant", "metadata update failed", 502)
        self.clearance_updates.append((doc_id, clearance_level, clearance_rank))

    def set_document_topics(self, doc_id: str, *, topics: list[str], llm_topics: list[str]) -> None:
        if self.fail_topics:
            raise ServiceRequestError("qdrant", "topic update failed", 502)
        self.topic_updates.append((doc_id, topics, llm_topics))

    def delete_document_points(self, doc_id: str) -> None:
        if self.fail_delete:
            raise ServiceRequestError("qdrant", "vector deletion failed", 502)
        self.deleted_documents.append(doc_id)


class FakeStorage:
    def __init__(self, *, read_error: str | None = None, delete_error: str | None = None) -> None:
        self.read_error = read_error
        self.delete_error = delete_error
        self.deleted: list[str] = []

    def read(self, object_path: str) -> StoredUploadContent:
        if self.read_error:
            raise RuntimeError(self.read_error)
        return StoredUploadContent(
            content=b"%PDF-1.7\nsource\n%%EOF",
            content_type="application/pdf",
            filename="document.pdf",
        )

    def delete(self, object_path: str) -> None:
        if self.delete_error:
            raise RuntimeError(self.delete_error)
        self.deleted.append(object_path)


class FakeImageStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, object_path: str) -> None:
        self.deleted.append(object_path)


class FakeIngestQueue:
    def __init__(self, *, error: str | None = None) -> None:
        self.error = error
        self.messages: list[IngestJobPayload] = []

    def enqueue(self, message: IngestJobPayload) -> None:
        if self.error:
            raise RuntimeError(self.error)
        self.messages.append(message)


class FakeGraphRAG:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_document(self, *, doc_id: str, partition_key: str) -> GraphRAGCleanupResult:
        self.deleted.append((doc_id, partition_key))
        return GraphRAGCleanupResult(
            status="complete",
            doc_id=doc_id,
            partition_key=partition_key,
        )


class FakeGraphQueue:
    def __init__(self, *, document_error: str | None = None) -> None:
        self.document_error = document_error
        self.document_messages: list[GraphRAGDocumentIndexMessage] = []
        self.partition_messages: list[GraphRAGPartitionRebuildMessage] = []

    def enqueue_document_index(self, message: GraphRAGDocumentIndexMessage) -> None:
        if self.document_error:
            raise RuntimeError(self.document_error)
        self.document_messages.append(message)

    def enqueue_partition_rebuild(self, message: GraphRAGPartitionRebuildMessage) -> None:
        self.partition_messages.append(message)


def test_clearance_update_persists_indexes_and_audits_success() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", clearance="NATO_SECRET")
    document = _document(repo, user=user)
    qdrant = FakeQdrant()

    response = asyncio.run(
        document_routes.update_document_clearance(
            document.id,
            DocumentClearanceUpdateRequest(clearance_level="NATO_CONFIDENTIAL"),
            _csrf_request("PATCH"),
            user=user,
            service=_metadata_service(repo, qdrant),
        )
    )

    assert response.clearance_level == "NATO_CONFIDENTIAL"
    assert repo.get_document(document.id).clearance_level == "NATO_CONFIDENTIAL"  # type: ignore[union-attr]
    assert qdrant.clearance_updates == [(document.id, "NATO_CONFIDENTIAL", 2)]
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_same_clearance_is_idempotent_without_index_or_audit_side_effects() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    qdrant = FakeQdrant()

    response = asyncio.run(
        document_routes.update_document_clearance(
            document.id,
            DocumentClearanceUpdateRequest(clearance_level="NATO_RESTRICTED"),
            _csrf_request("PATCH"),
            user=user,
            service=_metadata_service(repo, qdrant),
        )
    )

    assert response.clearance_level == "NATO_RESTRICTED"
    assert qdrant.clearance_updates == []
    assert repo.audit_events == []


def test_topic_index_failure_rolls_back_metadata_and_audits_failure() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    repo.update_document_topics(document.id, topics=["Old"], llm_topics=["LLM Old"])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.update_document_topics(
                document.id,
                DocumentTopicsUpdateRequest(topics=["New"], llm_topics=["LLM New"]),
                _csrf_request("PATCH"),
                user=user,
                service=_metadata_service(
                    repo,
                    FakeQdrant(fail_topics=True),
                ),
            )
        )

    current = repo.get_document(document.id)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "document_topics_index_update_failed"
    assert current is not None
    assert current.topics == ("Old",)
    assert current.llm_topics == ("LLM Old",)
    assert repo.audit_events[-1]["payload"]["action_result"] == "failed"


def test_metadata_update_rejects_non_writer_before_external_calls() -> None:
    repo = InMemoryDocumentRepository()
    owner = _user("contributor")
    member = _user("member")
    document = _document(repo, user=owner)
    qdrant = FakeQdrant()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.update_document_topics(
                document.id,
                DocumentTopicsUpdateRequest(topics=["New"]),
                _csrf_request("PATCH"),
                user=member,
                service=_metadata_service(repo, qdrant),
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "document_forbidden"
    assert qdrant.topic_updates == []


def _metadata_service(
    repo: InMemoryDocumentRepository,
    qdrant: FakeQdrant,
) -> DocumentMetadataService:
    return DocumentMetadataService(
        document_repo=repo,
        index=QdrantDocumentMetadataIndex(qdrant),  # type: ignore[arg-type]
    )


def test_reingest_queues_source_payload_and_audits_success() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    queue = FakeIngestQueue()

    response = asyncio.run(
        ingestion_document_routes.reingest_document(
            document.id,
            _csrf_request("POST"),
            user=user,
            service=_reingestion_service(repo, FakeStorage(), queue),
        )
    )

    job = repo.get_ingest_job(response.job_id)
    assert job is not None and job.status == "queued" and job.origin == "reingest"
    assert queue.messages[0].doc_id == document.id
    assert queue.messages[0].file_path == document.file_path
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_reingest_queue_failure_marks_job_failed_and_audits_failure() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            ingestion_document_routes.reingest_document(
                document.id,
                _csrf_request("POST"),
                user=user,
                service=_reingestion_service(
                    repo,
                    FakeStorage(),
                    FakeIngestQueue(error="redis unavailable"),
                ),
            )
        )

    jobs = repo.list_ingest_jobs()
    assert exc_info.value.status_code == 503
    assert len(jobs) == 1 and jobs[0].status == "failed"
    assert jobs[0].error_code == "queue_unavailable"
    assert repo.audit_events[-1]["payload"]["action_result"] == "failed"


def test_active_reingest_is_rejected_without_creating_another_job() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    existing = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="reingest")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            ingestion_document_routes.reingest_document(
                document.id,
                _csrf_request("POST"),
                user=user,
                service=_reingestion_service(
                    repo,
                    FakeStorage(),
                    FakeIngestQueue(),
                ),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "document_ingest_active"
    assert [job.id for job in repo.list_ingest_jobs()] == [existing.id]


def test_graph_enqueue_failure_returns_503_and_audits_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user, ingest_status="complete")
    job = repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            graphrag_document_routes.queue_document_graph_enrichment(
                document.id,
                _csrf_request("POST"),
                user=user,
                service=_graph_enrichment_service(
                    repo,
                    FakeGraphQueue(document_error="broker unavailable"),
                    enabled=True,
                ),
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "graphrag_enqueue_failed"
    assert repo.audit_events[-1]["event_type"] == "documents.graph_enrichment.enqueue_failed"
    assert repo.audit_events[-1]["payload"] == {"job_id": job.id, "error": "broker unavailable"}


def _reingestion_service(
    repo: InMemoryDocumentRepository,
    storage: FakeStorage,
    queue: FakeIngestQueue,
) -> DocumentReingestionService:
    return DocumentReingestionService(
        document_repo=repo,
        job_repo=repo,
        storage=storage,  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
    )


def _graph_enrichment_service(
    repo: InMemoryDocumentRepository,
    queue: FakeGraphQueue,
    *,
    enabled: bool,
) -> DocumentGraphEnrichmentService:
    return DocumentGraphEnrichmentService(
        document_repo=repo,
        job_repo=repo,
        queue=GraphRAGDocumentEnrichmentQueue(queue),  # type: ignore[arg-type]
        enrichment_enabled=lambda: enabled,
    )


def _lifecycle_service(
    repo: InMemoryDocumentRepository,
    *,
    storage: FakeStorage | None = None,
    image_storage: FakeImageStorage | None = None,
    ingest_queue: FakeIngestQueue | None = None,
    qdrant: FakeQdrant | None = None,
    graphrag: FakeGraphRAG | None = None,
    graph_queue: FakeGraphQueue | None = None,
) -> DocumentLifecycleService:
    return DocumentLifecycleService(
        documents=repo,
        jobs=repo,
        storage=storage or FakeStorage(),  # type: ignore[arg-type]
        image_storage=image_storage or FakeImageStorage(),
        ingest_queue=ingest_queue or FakeIngestQueue(),  # type: ignore[arg-type]
        vectors=QdrantDocumentVectorIndex(qdrant or FakeQdrant()),  # type: ignore[arg-type]
        graph_cleanup=GraphRAGDocumentStore(graphrag or FakeGraphRAG()),  # type: ignore[arg-type]
        graph_queue=GraphRAGPartitionRebuildQueue(
            graph_queue or FakeGraphQueue()  # type: ignore[arg-type]
        ),
        graphrag_enabled=True,
        qdrant_collection=settings.qdrant_collection,
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


def _csrf_request(method: str) -> Request:
    token = "csrf-test-token"
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": [
                (b"cookie", f"{settings.csrf_cookie_name}={token}".encode("ascii")),
                (b"x-csrf-token", token.encode("ascii")),
            ],
        }
    )


def _user(
    account_type: str,
    *,
    clearance: str = "NATO_RESTRICTED",
) -> UserRecord:
    return UserRecord(
        id=str(uuid4()),
        email=f"{uuid4()}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level=clearance,  # type: ignore[arg-type]
        must_change_password=False,
        permission_version=1,
        group_paths=("/ops",),
    )


def _document(
    repo: InMemoryDocumentRepository,
    *,
    user: UserRecord,
    ingest_status: str = "complete",
):
    return repo.create_document(
        title="Document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="report",
        effective_date=None,
        expiry_date=None,
        description="Characterization source",
        uploaded_by=user.id,
        file_path="memory://document.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status=ingest_status,
    )
