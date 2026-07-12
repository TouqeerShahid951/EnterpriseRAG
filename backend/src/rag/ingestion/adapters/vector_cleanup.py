"""Qdrant adapter for ingestion cancellation cleanup."""

from __future__ import annotations

from ..cancellation import DocumentVectorCleanupError
from ..indexing.qdrant import QdrantClient
from .http import ServiceRequestError


class QdrantDocumentVectorCleaner:
    def __init__(
        self,
        *,
        base_url: str,
        collection: str,
        timeout_seconds: float,
    ) -> None:
        self._client = QdrantClient(
            base_url=base_url,
            collection=collection,
            timeout_seconds=timeout_seconds,
        )

    def delete_document_vectors(self, document_id: str) -> None:
        try:
            self._client.delete_document_points(document_id)
        except ServiceRequestError as exc:
            raise DocumentVectorCleanupError(exc.message[:300]) from exc
