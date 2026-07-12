"""Ingestion-job repository composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from .document_models import DocumentRepository
from .document_postgres import PostgresDocumentRepository
from .documents import get_document_repository
from .ingest_job_models import IngestJobRepository
from .ingest_job_postgres import PostgresIngestJobRepository


def ingest_job_repository_for(
    document_repo: DocumentRepository,
) -> IngestJobRepository:
    """Resolve the job adapter paired with an existing document adapter."""

    if isinstance(document_repo, PostgresDocumentRepository):
        return PostgresIngestJobRepository(document_repo.database_url)
    if isinstance(document_repo, IngestJobRepository):
        return document_repo
    raise RuntimeError(
        "ingestion-job repository must be configured for this document adapter"
    )


def get_ingest_job_repository(
    document_repo: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
) -> IngestJobRepository:
    return ingest_job_repository_for(document_repo)


__all__ = [
    "IngestJobRepository",
    "PostgresIngestJobRepository",
    "get_ingest_job_repository",
    "ingest_job_repository_for",
]
