"""Public identity repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .identity_memory import InMemoryIdentityRepository
from .identity_models import GroupRecord, IdentityRepository, UserRecord
from .identity_postgres import PostgresIdentityRepository


@lru_cache
def default_identity_repository() -> IdentityRepository:
    if settings.identity_repository == "memory":
        return InMemoryIdentityRepository()
    return PostgresIdentityRepository(settings.database_url)


def get_identity_repository() -> IdentityRepository:
    return default_identity_repository()


__all__ = [
    "GroupRecord",
    "IdentityRepository",
    "InMemoryIdentityRepository",
    "PostgresIdentityRepository",
    "UserRecord",
    "default_identity_repository",
    "get_identity_repository",
]
