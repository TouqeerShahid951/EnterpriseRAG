"""Outbound contracts used by document lifecycle workflows."""

from __future__ import annotations

from typing import Protocol

from rag.documents.access_scope.ports import DocumentGraphCleanupResult
from rag.documents.models import DocumentRecord


class DocumentVectorIndexError(RuntimeError):
    """The document vector index rejected a lifecycle operation."""


class DocumentVectorIndex(Protocol):
    def delete_document_points(self, document_id: str) -> None: ...


class DocumentGraphCleanup(Protocol):
    def partition_key_for(self, document: DocumentRecord) -> str: ...

    def delete_document(
        self,
        *,
        document_id: str,
        partition_key: str,
    ) -> DocumentGraphCleanupResult: ...


class GraphPartitionRebuildQueue(Protocol):
    def enqueue_partition_rebuild(
        self,
        *,
        document_id: str,
        partition_key: str,
        reason: str,
    ) -> None: ...


class DocumentImageDeletionStore(Protocol):
    def delete(self, object_path: str) -> None: ...
