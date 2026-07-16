"""Qdrant adapter for document metadata updates."""

from __future__ import annotations

from ...query.http import ServiceRequestError
from ...query.qdrant import QdrantClient
from ...shared.contracts.clearance import clearance_rank
from rag.documents.metadata.ports import DocumentMetadataIndexError


class QdrantDocumentMetadataIndex:
    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    @property
    def collection_name(self) -> str:
        return self._client.collection

    def set_clearance(
        self,
        document_id: str,
        clearance_level: str,
    ) -> None:
        try:
            self._client.set_document_clearance(
                document_id,
                clearance_level=clearance_level,
                clearance_rank=clearance_rank(clearance_level),
            )
        except ServiceRequestError as exc:
            raise DocumentMetadataIndexError(str(exc)) from exc

    def set_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
    ) -> None:
        try:
            self._client.set_document_topics(
                document_id,
                topics=topics,
                llm_topics=llm_topics,
            )
        except ServiceRequestError as exc:
            raise DocumentMetadataIndexError(str(exc)) from exc
