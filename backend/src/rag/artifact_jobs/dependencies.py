"""Composition providers for the artifact-generation feature."""

from __future__ import annotations

from functools import lru_cache

from ..auth.identity_repository import get_identity_repository
from ..core.config import Settings, settings
from ..documents.repository import get_document_repository
from ..query.inference import build_inference_client
from ..query.qdrant import QdrantClient
from ..query.rag_config_repository import effective_rag_config
from .adapters.generated_memory import InMemoryGeneratedArtifactRepository
from .adapters.generated_postgres import PostgresGeneratedArtifactRepository
from .adapters.internal_context_http import HttpArtifactContextValidator
from .adapters.job_memory import InMemoryArtifactJobRepository
from .adapters.job_postgres import PostgresArtifactJobRepository
from .adapters.queue import CeleryArtifactJobQueue, InMemoryArtifactJobQueue
from .adapters.storage import (
    LocalGeneratedArtifactStorage,
    MinioGeneratedArtifactStorage,
)
from .cleanup import GeneratedArtifactCleanupService
from .execution import ArtifactJobExecutor
from .generated_models import GeneratedArtifactRepository
from .job_models import ArtifactJobRepository
from .queue import ArtifactJobQueue
from .service import ArtifactJobService
from .storage import GeneratedArtifactStorage
from .task_execution import ArtifactContextValidator


def build_artifact_job_repository(config: Settings) -> ArtifactJobRepository:
    if config.document_repository == "memory":
        return InMemoryArtifactJobRepository()
    return PostgresArtifactJobRepository(config.database_url)


@lru_cache
def default_artifact_job_repository() -> ArtifactJobRepository:
    return build_artifact_job_repository(settings)


def get_artifact_job_repository() -> ArtifactJobRepository:
    return default_artifact_job_repository()


def build_generated_artifact_repository(
    config: Settings,
) -> GeneratedArtifactRepository:
    if config.document_repository == "memory":
        return InMemoryGeneratedArtifactRepository(config.artifact_retention_days)
    return PostgresGeneratedArtifactRepository(
        config.database_url,
        default_retention_days=config.artifact_retention_days,
    )


@lru_cache
def default_generated_artifact_repository() -> GeneratedArtifactRepository:
    return build_generated_artifact_repository(settings)


def get_generated_artifact_repository() -> GeneratedArtifactRepository:
    return default_generated_artifact_repository()


def build_generated_artifact_storage(config: Settings) -> GeneratedArtifactStorage:
    if config.upload_storage_backend == "minio":
        return MinioGeneratedArtifactStorage(
            endpoint=config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            bucket=config.minio_bucket,
            secure=config.minio_secure,
        )
    if config.upload_storage_backend != "local":
        raise RuntimeError(
            "unsupported generated artifact storage backend: "
            f"{config.upload_storage_backend}"
        )
    return LocalGeneratedArtifactStorage(config.upload_storage_dir)


@lru_cache
def default_generated_artifact_storage() -> GeneratedArtifactStorage:
    return build_generated_artifact_storage(settings)


def get_generated_artifact_storage() -> GeneratedArtifactStorage:
    return default_generated_artifact_storage()


def build_artifact_job_queue(config: Settings) -> ArtifactJobQueue:
    if config.artifact_queue_backend == "memory":
        return InMemoryArtifactJobQueue()
    if config.artifact_queue_backend != "celery":
        raise RuntimeError(
            f"unsupported artifact queue backend: {config.artifact_queue_backend}"
        )
    return CeleryArtifactJobQueue(
        broker_url=config.celery_broker_url or config.redis_url,
        queue_name=config.artifact_queue_name,
        task_name=config.artifact_task_name,
    )


@lru_cache
def default_artifact_job_queue() -> ArtifactJobQueue:
    return build_artifact_job_queue(settings)


def get_artifact_job_queue() -> ArtifactJobQueue:
    return default_artifact_job_queue()


def get_artifact_job_service() -> ArtifactJobService:
    return ArtifactJobService(
        repo_factory=get_artifact_job_repository,
        artifact_repo_factory=get_generated_artifact_repository,
        queue_factory=get_artifact_job_queue,
        retention_days=settings.artifact_retention_days,
    )


def get_artifact_job_executor(config: Settings | None = None) -> ArtifactJobExecutor:
    selected = config or settings
    rag_config = effective_rag_config(config=selected)
    inference = build_inference_client(rag_config, settings=selected)
    return ArtifactJobExecutor(
        config=selected,
        repo_factory=get_artifact_job_repository,
        artifact_repo_factory=get_generated_artifact_repository,
        storage_factory=get_generated_artifact_storage,
        identity_repo_factory=get_identity_repository,
        document_repo_factory=get_document_repository,
        inference=inference,
        qdrant=QdrantClient(
            base_url=selected.qdrant_url,
            collection=selected.qdrant_collection,
            timeout_seconds=selected.rag_http_timeout_seconds,
        ),
        model_name=rag_config.effective_reasoning_model or rag_config.chat_model,
        rag_config=rag_config,
    )


def get_artifact_context_validator() -> ArtifactContextValidator:
    return HttpArtifactContextValidator(
        base_url=settings.backend_internal_url,
        service_token=settings.service_token,
        timeout_seconds=settings.rag_http_timeout_seconds,
    )


def get_generated_artifact_cleanup_service() -> GeneratedArtifactCleanupService:
    return GeneratedArtifactCleanupService(
        repository_factory=get_generated_artifact_repository,
        storage_factory=get_generated_artifact_storage,
        job_repository_factory=get_artifact_job_repository,
    )
