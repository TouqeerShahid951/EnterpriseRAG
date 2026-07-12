from __future__ import annotations

import pytest

from rag.documents import IngestJobRecord as CapabilityIngestJobRecord
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.repositories.document_models import IngestJobRecord as DocumentModelIngestJobRecord
from rag.repositories.document_postgres import (
    PostgresDocumentRepository,
    job_from_row as document_job_from_row,
)
from rag.repositories.documents import IngestJobRecord as DocumentFacadeIngestJobRecord
from rag.repositories.ingest_job_models import IngestJobRecord
from rag.repositories.ingest_job_postgres import (
    PostgresIngestJobRepository,
    job_from_row,
)
from rag.repositories.ingest_jobs import ingest_job_repository_for


def test_memory_provider_reuses_document_repository_instance() -> None:
    document_repo = InMemoryDocumentRepository()

    assert ingest_job_repository_for(document_repo) is document_repo


def test_postgres_provider_uses_same_database_url() -> None:
    document_repo = PostgresDocumentRepository("postgresql://repository.test/db")

    job_repo = ingest_job_repository_for(document_repo)

    assert isinstance(job_repo, PostgresIngestJobRepository)
    assert job_repo.database_url == document_repo.database_url


def test_provider_rejects_unsupported_document_adapter() -> None:
    with pytest.raises(
        RuntimeError,
        match="ingestion-job repository must be configured for this document adapter",
    ):
        ingest_job_repository_for(object())  # type: ignore[arg-type]


def test_legacy_ingest_job_record_exports_alias_canonical_record() -> None:
    assert DocumentModelIngestJobRecord is IngestJobRecord
    assert DocumentFacadeIngestJobRecord is IngestJobRecord
    assert CapabilityIngestJobRecord is IngestJobRecord


def test_legacy_document_job_row_mapper_aliases_canonical_mapper() -> None:
    assert document_job_from_row is job_from_row
