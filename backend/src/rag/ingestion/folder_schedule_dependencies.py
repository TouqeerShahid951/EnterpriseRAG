"""Composition provider for folder-ingestion schedule persistence."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .adapters.folder_schedule_memory import InMemoryFolderScheduleRepository
from .adapters.folder_schedule_postgres import PostgresFolderScheduleRepository
from .folder_schedule_models import FolderScheduleRepository


@lru_cache
def default_folder_schedule_repository() -> FolderScheduleRepository:
    if settings.document_repository == "memory":
        return InMemoryFolderScheduleRepository()
    return PostgresFolderScheduleRepository(settings.database_url)


def get_folder_schedule_repository() -> FolderScheduleRepository:
    return default_folder_schedule_repository()
