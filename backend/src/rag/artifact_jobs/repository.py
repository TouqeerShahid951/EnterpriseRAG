"""Public artifact-generation job repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .adapters.job_memory import InMemoryArtifactJobRepository
from .adapters.job_postgres import (
    ARTIFACT_JOB_SCHEMA_SQL,
    PostgresArtifactJobRepository,
    artifact_job_from_row,
)
from .job_models import (
    ACTIVE_ARTIFACT_JOB_STATUSES,
    DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT,
    TERMINAL_ARTIFACT_JOB_STATUSES,
    ArtifactJobRecord,
    ArtifactJobRepository,
)


@lru_cache
def default_artifact_job_repository() -> ArtifactJobRepository:
    if settings.document_repository == "memory":
        return InMemoryArtifactJobRepository()
    return PostgresArtifactJobRepository(settings.database_url)


def get_artifact_job_repository() -> ArtifactJobRepository:
    return default_artifact_job_repository()


__all__ = [
    "ACTIVE_ARTIFACT_JOB_STATUSES",
    "ARTIFACT_JOB_SCHEMA_SQL",
    "DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT",
    "TERMINAL_ARTIFACT_JOB_STATUSES",
    "ArtifactJobRecord",
    "ArtifactJobRepository",
    "InMemoryArtifactJobRepository",
    "PostgresArtifactJobRepository",
    "artifact_job_from_row",
    "default_artifact_job_repository",
    "get_artifact_job_repository",
]
