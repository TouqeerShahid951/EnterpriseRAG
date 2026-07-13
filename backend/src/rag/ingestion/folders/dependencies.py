"""Composition providers for scheduled folder ingestion."""

from __future__ import annotations

from functools import lru_cache

from ...core.config import settings
from .adapters.memory import InMemoryFolderScheduleRepository
from .adapters.postgres import PostgresFolderScheduleRepository
from .adapters.sources import LocalFileSystemSource, MinioObjectSource
from .config import FolderIngestionConfig
from .models import FolderScheduleRepository
from .sources import LocalFolderSource, MinioPrefixSource


def get_folder_ingestion_config() -> FolderIngestionConfig:
    return FolderIngestionConfig(
        default_timezone=settings.workspace_timezone,
        sources_root=settings.folder_sources_root,
        snapshot_max_files=settings.folder_snapshot_max_files,
        snapshot_max_bytes=settings.folder_snapshot_max_bytes,
        upload_max_bytes=settings.upload_max_bytes,
    )


def get_minio_prefix_source() -> MinioPrefixSource:
    return MinioObjectSource(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def get_local_folder_source() -> LocalFolderSource:
    return LocalFileSystemSource()


@lru_cache
def default_folder_schedule_repository() -> FolderScheduleRepository:
    if settings.document_repository == "memory":
        return InMemoryFolderScheduleRepository()
    return PostgresFolderScheduleRepository(settings.database_url)


def get_folder_schedule_repository() -> FolderScheduleRepository:
    return default_folder_schedule_repository()
