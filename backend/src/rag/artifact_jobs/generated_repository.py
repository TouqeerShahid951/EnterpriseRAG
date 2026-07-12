"""Public generated artifact repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .adapters.generated_memory import InMemoryGeneratedArtifactRepository
from .adapters.generated_postgres import PostgresGeneratedArtifactRepository
from .generated_models import GeneratedArtifactRecord, GeneratedArtifactRepository


@lru_cache
def default_generated_artifact_repository() -> GeneratedArtifactRepository:
    if settings.document_repository == "memory":
        return InMemoryGeneratedArtifactRepository(settings.artifact_retention_days)
    return PostgresGeneratedArtifactRepository(
        settings.database_url,
        default_retention_days=settings.artifact_retention_days,
    )


def get_generated_artifact_repository() -> GeneratedArtifactRepository:
    return default_generated_artifact_repository()


__all__ = [
    "GeneratedArtifactRecord",
    "GeneratedArtifactRepository",
    "InMemoryGeneratedArtifactRepository",
    "PostgresGeneratedArtifactRepository",
    "get_generated_artifact_repository",
]
