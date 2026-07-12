"""Ingestion-job repository composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from ..repositories.document_memory import InMemoryDocumentRepository
from ..repositories.document_models import DocumentRepository
from ..repositories.document_postgres import PostgresDocumentRepository
from ..repositories.documents import get_document_repository
from .adapters.job_postgres import PostgresIngestJobRepository
from .job_models import IngestJobStore


def ingest_job_repository_for(document_repo: DocumentRepository) -> IngestJobStore:
    if isinstance(document_repo, PostgresDocumentRepository):
        return PostgresIngestJobRepository(document_repo.database_url)
    if isinstance(document_repo, InMemoryDocumentRepository):
        return document_repo
    raise RuntimeError(
        "ingestion-job repository must be configured for this document adapter"
    )


def get_ingest_job_repository(
    document_repo: Annotated[DocumentRepository, Depends(get_document_repository)],
) -> IngestJobStore:
    return ingest_job_repository_for(document_repo)
