"""Public folder schedule repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .folder_schedule_memory import InMemoryFolderScheduleRepository
from .folder_schedule_models import FolderRunItemRecord, FolderRunRecord, FolderScheduleRecord, FolderScheduleRepository
from .folder_schedule_postgres import PostgresFolderScheduleRepository


@lru_cache
def default_folder_schedule_repository() -> FolderScheduleRepository:
    if settings.document_repository == "memory":
        return InMemoryFolderScheduleRepository()
    return PostgresFolderScheduleRepository(settings.database_url)


def get_folder_schedule_repository() -> FolderScheduleRepository:
    return default_folder_schedule_repository()


__all__ = [
    "FolderRunItemRecord",
    "FolderRunRecord",
    "FolderScheduleRecord",
    "FolderScheduleRepository",
    "InMemoryFolderScheduleRepository",
    "PostgresFolderScheduleRepository",
    "get_folder_schedule_repository",
]

