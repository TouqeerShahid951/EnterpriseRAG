"""Composition providers for ingestion checkpoints."""

from fastapi import Depends

from rag.core.config import settings
from rag.documents.repository import get_document_repository

from .adapters.postgres import PostgresCheckpointRepository
from .repository import CheckpointRepository
from .service import CheckpointService


def get_checkpoint_repository(
    document_repo=Depends(get_document_repository),
) -> CheckpointRepository:
    return PostgresCheckpointRepository(settings.database_url) if settings.document_repository == "postgres" else _UnsupportedCheckpointRepository()


def get_checkpoint_service(
    repository: CheckpointRepository = Depends(get_checkpoint_repository),
) -> CheckpointService:
    # The API commits references after the worker uploads the immutable object.
    return CheckpointService(repository, None)


class _UnsupportedCheckpointRepository:
    def commit(self, *args, **kwargs):
        raise RuntimeError("ingestion checkpoints require the postgres repository")

    def invalidate(self, *args, **kwargs):
        raise RuntimeError("ingestion checkpoints require the postgres repository")

    def get(self, *args, **kwargs):
        return None

    def list(self, *args, **kwargs):
        return ()

    def expired(self, *args, **kwargs):
        return ()

    def delete(self, *args, **kwargs):
        return False
