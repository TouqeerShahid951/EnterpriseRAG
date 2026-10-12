"""Composition providers for workspace branding."""

from functools import lru_cache

from rag.core.config import settings

from .adapters.memory import InMemoryBrandingRepository
from .adapters.postgres import PostgresBrandingRepository
from .models import BrandingRepository


@lru_cache
def get_branding_repository() -> BrandingRepository:
    if settings.document_repository == "memory":
        return InMemoryBrandingRepository()
    return PostgresBrandingRepository(settings.database_url)
