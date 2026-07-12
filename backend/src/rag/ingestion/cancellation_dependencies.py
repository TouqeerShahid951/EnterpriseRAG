"""Composition provider for ingestion-cancellation adapters."""

from functools import lru_cache

from ..core.config import settings
from .adapters.vector_cleanup import QdrantDocumentVectorCleaner
from .cancellation import DocumentVectorCleaner


@lru_cache
def get_document_vector_cleaner() -> DocumentVectorCleaner:
    return QdrantDocumentVectorCleaner(
        base_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        timeout_seconds=settings.rag_http_timeout_seconds,
    )
