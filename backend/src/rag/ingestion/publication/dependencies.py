"""Composition helpers for index publication."""

from __future__ import annotations

from collections.abc import Callable

from rag.core.config import Settings, settings

from .adapters.postgres import PostgresIndexPublicationRepository
from .service import IndexPublicationService


def publication_service_for(config: Settings) -> IndexPublicationService:
    if config.document_repository != "postgres":
        raise RuntimeError("index generation publication requires the postgres document repository")
    return IndexPublicationService(PostgresIndexPublicationRepository(config.database_url))


def get_index_publication_service() -> IndexPublicationService:
    return publication_service_for(settings)


def active_generation_resolver_for(
    config: Settings,
) -> Callable[[list[str], bool], dict[str, str | None]] | None:
    if config.document_repository != "postgres":
        return None
    repository = PostgresIndexPublicationRepository(config.database_url)
    return repository.active_generation_ids
