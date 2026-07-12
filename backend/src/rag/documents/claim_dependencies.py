"""Composition provider for document claim persistence."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import Settings, settings
from .adapters.claim_memory import InMemoryClaimRepository
from .adapters.claim_postgres import PostgresClaimRepository
from .claim_models import ClaimRepository


def claim_repository_from_settings(config: Settings) -> ClaimRepository:
    if config.document_repository == "memory":
        return InMemoryClaimRepository()
    return PostgresClaimRepository(config.database_url)


@lru_cache
def default_claim_repository() -> ClaimRepository:
    return claim_repository_from_settings(settings)


def get_claim_repository() -> ClaimRepository:
    return default_claim_repository()


__all__ = [
    "ClaimRepository",
    "InMemoryClaimRepository",
    "PostgresClaimRepository",
    "claim_repository_from_settings",
    "get_claim_repository",
]
