"""Composition helpers for index publication."""

from __future__ import annotations

from collections.abc import Callable

from rag.core.config import Settings, settings

from .adapters.postgres import PostgresIndexPublicationRepository
from .repository import IndexPublicationRepository


def publication_repository_for(config: Settings) -> IndexPublicationRepository:
    if config.document_repository != "postgres":
        raise RuntimeError("index generation publication requires the postgres document repository")
    return PostgresIndexPublicationRepository(config.database_url)


def get_index_publication_repository() -> IndexPublicationRepository:
    return publication_repository_for(settings)


def active_generation_resolver_for(
    config: Settings,
) -> Callable[[list[str], bool], dict[str, str | None]] | None:
    if config.document_repository != "postgres":
        return None
    repository = PostgresIndexPublicationRepository(config.database_url)
    return repository.active_generation_ids
