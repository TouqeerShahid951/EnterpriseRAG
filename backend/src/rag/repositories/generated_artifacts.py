"""Public generated artifact repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .generated_artifact_memory import InMemoryGeneratedArtifactRepository
from .generated_artifact_models import GeneratedArtifactRecord, GeneratedArtifactRepository
from .generated_artifact_postgres import PostgresGeneratedArtifactRepository


@lru_cache
def default_generated_artifact_repository() -> GeneratedArtifactRepository:
    if settings.document_repository == "memory":
        return InMemoryGeneratedArtifactRepository()
    return PostgresGeneratedArtifactRepository(settings.database_url)


def get_generated_artifact_repository() -> GeneratedArtifactRepository:
    return default_generated_artifact_repository()


__all__ = [
    "GeneratedArtifactRecord",
    "GeneratedArtifactRepository",
    "InMemoryGeneratedArtifactRepository",
    "PostgresGeneratedArtifactRepository",
    "get_generated_artifact_repository",
]
