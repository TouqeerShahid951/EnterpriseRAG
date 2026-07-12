"""Ingestion-job repository composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from ..documents.adapters.memory import InMemoryDocumentRepository
from ..documents.models import DocumentRepository
from ..documents.adapters.postgres import PostgresDocumentRepository
from ..documents.repository import get_document_repository
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
