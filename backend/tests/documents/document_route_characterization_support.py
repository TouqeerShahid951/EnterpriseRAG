"""Fakes and service builders for document-route characterization tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request

from rag.auth.identity_models import UserRecord
from rag.core.config import settings
from rag.documents.adapters.access_scope_graph import GraphRAGDocumentStore
from rag.documents.adapters.lifecycle import GraphRAGPartitionRebuildQueue, QdrantDocumentVectorIndex
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.adapters.metadata_index import QdrantDocumentMetadataIndex
from rag.documents.lifecycle.service import DocumentLifecycleService
from rag.documents.metadata.service import DocumentMetadataService
from rag.documents.lifecycle.reingestion_service import DocumentReingestionService
from rag.documents.storage import StoredUploadContent
from rag.graphrag.adapters.document_enrichment_queue import GraphRAGDocumentEnrichmentQueue
from rag.graphrag.cleanup import GraphRAGCleanupResult
from rag.graphrag.document_enrichment_service import DocumentGraphEnrichmentService
from rag.graphrag.maintenance_queue import GraphRAGDocumentIndexMessage, GraphRAGPartitionRebuildMessage
from rag.ingestion.contracts import IngestJobPayload
from rag.query.http import ServiceRequestError


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

def _metadata_service(
    repo: InMemoryDocumentRepository,
    qdrant: FakeQdrant,
) -> DocumentMetadataService:
    return DocumentMetadataService(
        document_repo=repo,
        index=QdrantDocumentMetadataIndex(qdrant),  # type: ignore[arg-type]
    )
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
