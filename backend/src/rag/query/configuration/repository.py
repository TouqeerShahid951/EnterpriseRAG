"""Public workspace RAG configuration repository dependency."""

from __future__ import annotations

from functools import lru_cache

from rag.core.config import Settings, settings
from rag.query.adapters.rag_config_memory import InMemoryRagConfigRepository
from rag.query.adapters.rag_config_postgres import PostgresRagConfigRepository
from .models import DEFAULT_OLLAMA_PORT, DEFAULT_VLLM_PORT, RagConfigRecord, RagConfigRepository
from .validation import env_rag_config, normalize_inference_base_url, normalize_ollama_base_url


def effective_rag_config(
    *,
    config: Settings = settings,
    repo: RagConfigRepository | None = None,
) -> RagConfigRecord:
    repository = repo or rag_config_repository_from_settings(config)
    active = repository.get_active()
    return active if active else env_rag_config(config)


def rag_config_repository_from_settings(config: Settings) -> RagConfigRepository:
    if config.document_repository == "memory":
        return InMemoryRagConfigRepository()
    return PostgresRagConfigRepository(config.database_url)


@lru_cache
def default_rag_config_repository() -> RagConfigRepository:
    return rag_config_repository_from_settings(settings)


def get_rag_config_repository() -> RagConfigRepository:
    return default_rag_config_repository()


__all__ = [
    "DEFAULT_OLLAMA_PORT",
    "DEFAULT_VLLM_PORT",
    "InMemoryRagConfigRepository",
    "PostgresRagConfigRepository",
    "RagConfigRecord",
    "RagConfigRepository",
    "default_rag_config_repository",
    "effective_rag_config",
    "env_rag_config",
    "get_rag_config_repository",
    "normalize_ollama_base_url",
    "normalize_inference_base_url",
    "rag_config_repository_from_settings",
]
