"""Public query analytics repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ...core.config import Settings, settings
from .adapters.memory import InMemoryAnalyticsRepository
from .adapters.postgres import PostgresAnalyticsRepository
from .models import AnalyticsExecutionRepository


_memory_repository = InMemoryAnalyticsRepository()


def analytics_repository_from_settings() -> AnalyticsExecutionRepository:
    return analytics_repository_from_config(settings)


def analytics_repository_from_config(config: Settings) -> AnalyticsExecutionRepository:
    if config.document_repository == "memory":
        return _memory_repository
    return PostgresAnalyticsRepository(config.database_url)


@lru_cache
def default_analytics_repository() -> AnalyticsExecutionRepository:
    return analytics_repository_from_settings()


def get_analytics_repository() -> AnalyticsExecutionRepository:
    return default_analytics_repository()
