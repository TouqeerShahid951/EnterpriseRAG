"""GraphRAG maintenance-queue adapter for document enrichment."""

from ..maintenance_queue import (
    GraphRAGDocumentIndexMessage,
    GraphRAGMaintenanceQueue,
)


class GraphRAGDocumentEnrichmentQueue:
    def __init__(self, queue: GraphRAGMaintenanceQueue) -> None:
        self._queue = queue

    def enqueue(
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
