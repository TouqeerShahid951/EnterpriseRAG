"""Concrete outbound adapters for document lifecycle workflows."""

from __future__ import annotations

from ...query.http import ServiceRequestError
from ...query.qdrant import QdrantClient
from ...services.graphrag_queue import (
    GraphRAGMaintenanceQueue,
    GraphRAGPartitionRebuildMessage,
)
from ..lifecycle_ports import DocumentVectorIndexError


class QdrantDocumentVectorIndex:
    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def delete_document_points(self, document_id: str) -> None:
        try:
            self._client.delete_document_points(document_id)
        except ServiceRequestError as exc:
            raise DocumentVectorIndexError(str(exc)) from exc


class GraphRAGPartitionRebuildQueue:
    def __init__(self, queue: GraphRAGMaintenanceQueue) -> None:
        self._queue = queue

    def enqueue_partition_rebuild(
        self,
        *,
        document_id: str,
        partition_key: str,
        reason: str,
    ) -> None:
        self._queue.enqueue_partition_rebuild(
            GraphRAGPartitionRebuildMessage(
                doc_id=document_id,
                partition_key=partition_key,
                reason=reason,
            )
        )
