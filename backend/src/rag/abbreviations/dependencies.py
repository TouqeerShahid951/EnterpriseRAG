"""Composition providers for abbreviation glossary workflows."""

from functools import lru_cache

from fastapi import Depends

from rag.core.config import settings

from .adapters.memory import InMemoryAbbreviationRepository
from .adapters.postgres import PostgresAbbreviationRepository
from .models import AbbreviationRepository
from .service import AbbreviationGlossaryService


@lru_cache
def abbreviation_repository_from_settings() -> AbbreviationRepository:
    if settings.document_repository == "memory":
        return InMemoryAbbreviationRepository()
    return PostgresAbbreviationRepository(database_url=settings.database_url)


def get_abbreviation_repository() -> AbbreviationRepository:
    return abbreviation_repository_from_settings()


def get_abbreviation_service(
    repository: AbbreviationRepository = Depends(get_abbreviation_repository),
) -> AbbreviationGlossaryService:
    return AbbreviationGlossaryService(repository)

