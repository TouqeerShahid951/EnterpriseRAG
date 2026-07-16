"""Composition provider for document metadata workflows."""

from __future__ import annotations

from fastapi import Depends

from rag.core.config import settings
from rag.query.qdrant import QdrantClient
from rag.documents.adapters.metadata_index import QdrantDocumentMetadataIndex
from rag.documents.metadata.ports import DocumentMetadataIndex
from rag.documents.metadata.service import DocumentMetadataService
from rag.documents.models import DocumentRepository
from rag.documents.repository import get_document_repository


def get_document_metadata_index() -> DocumentMetadataIndex:
    return QdrantDocumentMetadataIndex(
        QdrantClient(
            base_url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            timeout_seconds=settings.rag_http_timeout_seconds,
        )
    )


def get_document_metadata_service(
    document_repo: DocumentRepository = Depends(get_document_repository),
    index: DocumentMetadataIndex = Depends(get_document_metadata_index),
) -> DocumentMetadataService:
    return DocumentMetadataService(
        document_repo=document_repo,
        index=index,
    )
