"""Public document repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .document_memory import InMemoryDocumentRepository
from .document_models import AuditEventRecord, DocumentImageAssetRecord, DocumentRecord, DocumentRepository, IngestJobRecord, ReviewBatchRecord, ReviewDecisionRecord, ReviewItemRecord
from .document_postgres import PostgresDocumentRepository


@lru_cache
def default_document_repository() -> DocumentRepository:
    if settings.document_repository == "memory":
        return InMemoryDocumentRepository()
    return PostgresDocumentRepository(settings.database_url)


def get_document_repository() -> DocumentRepository:
    return default_document_repository()


__all__ = [
    "DocumentRecord",
    "DocumentImageAssetRecord",
    "DocumentRepository",
    "AuditEventRecord",
    "InMemoryDocumentRepository",
    "IngestJobRecord",
    "ReviewBatchRecord",
    "ReviewDecisionRecord",
    "ReviewItemRecord",
    "PostgresDocumentRepository",
    "get_document_repository",
]
