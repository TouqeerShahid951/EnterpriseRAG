"""Qdrant adapter for cancelling only an unfinished index generation."""

from __future__ import annotations

from ..cancellation import DocumentVectorCleanupError
from ..indexing.qdrant import QdrantClient
from ..publication.service import IndexPublicationService
from .http import ServiceRequestError


class QdrantBuildingGenerationCleaner:
    def __init__(
        self,
        *,
        base_url: str,
        collection: str,
        timeout_seconds: float,
        publication_service: IndexPublicationService,
    ) -> None:
        self._publication_service = publication_service
        self._client = QdrantClient(
            base_url=base_url,
            collection=collection,
            timeout_seconds=timeout_seconds,
        )

    def delete_building_vectors(self, job_id: str) -> None:
        generation_id = self._publication_service.cancel_building(job_id=job_id)
        if generation_id is None:
            return
        try:
            self._client.delete_generation_points(generation_id)
        except ServiceRequestError as exc:
            raise DocumentVectorCleanupError(exc.message[:300]) from exc
