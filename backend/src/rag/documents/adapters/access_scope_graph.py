"""GraphRAG adapters for document owner-transfer refreshes."""

from __future__ import annotations

from ...graphrag.cleanup import (
    GraphRAGCleanupError,
    GraphRAGDeletionService,
    partition_key_for_document,
)
from ...services.graphrag_queue import (
    GraphRAGDocumentIndexMessage,
    GraphRAGMaintenanceQueue,
)
from ..access_scope_ports import (
    DocumentGraphCleanupError,
    DocumentGraphCleanupResult,
)
from ..models import DocumentRecord


class GraphRAGDocumentStore:
    def __init__(self, service: GraphRAGDeletionService) -> None:
        self._service = service

    def partition_key_for(self, document: DocumentRecord) -> str:
        return partition_key_for_document(document)

    def delete_document(
        self,
        *,
        document_id: str,
        partition_key: str,
    ) -> DocumentGraphCleanupResult:
        try:
            result = self._service.delete_document(
                doc_id=document_id,
                partition_key=partition_key,
            )
        except GraphRAGCleanupError as exc:
            raise DocumentGraphCleanupError(str(exc)) from exc
        return DocumentGraphCleanupResult(
            status=result.status,
            partition_key=result.partition_key,
        )


class GraphRAGDocumentIndexQueue:
    def __init__(self, queue: GraphRAGMaintenanceQueue) -> None:
        self._queue = queue

    def enqueue_document(
        self,
        *,
        document_id: str,
        job_id: str,
        reason: str,
    ) -> None:
        self._queue.enqueue_document_index(
            GraphRAGDocumentIndexMessage(
                doc_id=document_id,
                job_id=job_id,
                reason=reason,
            )
        )
