"""Public desired vLLM deployment configuration dependency."""

from __future__ import annotations

from functools import lru_cache

from rag.core.config import Settings, settings
from .adapters.vllm_config_memory import InMemoryVllmDeploymentConfigRepository
from .adapters.vllm_config_postgres import PostgresVllmDeploymentConfigRepository
from .vllm_config_models import (
    VllmDeploymentConfigRecord,
    VllmDeploymentConfigRepository,
    VllmServiceLimitsRecord,
)


def effective_vllm_deployment_config(
    *,
    config: Settings = settings,
    repo: VllmDeploymentConfigRepository | None = None,
) -> VllmDeploymentConfigRecord:
    repository = repo or vllm_deployment_config_repository_from_settings(config)
    return repository.get_active() or env_vllm_deployment_config(config)


def env_vllm_deployment_config(
    config: Settings = settings,
) -> VllmDeploymentConfigRecord:
    return VllmDeploymentConfigRecord(
        text=VllmServiceLimitsRecord(
            max_model_len=config.vllm_text_max_model_len,
            gpu_memory_utilization=config.vllm_text_gpu_memory_utilization,
            kv_cache_memory_bytes=config.vllm_text_kv_cache_memory_bytes,
            max_num_seqs=config.vllm_text_max_num_seqs,
            max_num_batched_tokens=config.vllm_text_max_num_batched_tokens,
        ),
        embeddings=VllmServiceLimitsRecord(
            max_model_len=config.vllm_embed_max_model_len,
            gpu_memory_utilization=config.vllm_embed_gpu_memory_utilization,
            max_num_seqs=config.vllm_embed_max_num_seqs,
            max_num_batched_tokens=config.vllm_embed_max_num_batched_tokens,
        ),
        vision=VllmServiceLimitsRecord(
            max_model_len=config.vllm_vision_max_model_len,
            gpu_memory_utilization=config.vllm_vision_gpu_memory_utilization,
            kv_cache_memory_bytes=config.vllm_vision_kv_cache_memory_bytes,
            max_num_seqs=config.vllm_vision_max_num_seqs,
            max_num_batched_tokens=config.vllm_vision_max_num_batched_tokens,
        ),
        source="environment",
    )


def vllm_deployment_config_repository_from_settings(
    config: Settings,
) -> VllmDeploymentConfigRepository:
    if config.document_repository == "memory":
        return InMemoryVllmDeploymentConfigRepository()
    return PostgresVllmDeploymentConfigRepository(config.database_url)


@lru_cache
def default_vllm_deployment_config_repository() -> VllmDeploymentConfigRepository:
    return vllm_deployment_config_repository_from_settings(settings)


def get_vllm_deployment_config_repository() -> VllmDeploymentConfigRepository:
    return default_vllm_deployment_config_repository()


__all__ = [
    "InMemoryVllmDeploymentConfigRepository",
    "PostgresVllmDeploymentConfigRepository",
    "VllmDeploymentConfigRecord",
    "VllmDeploymentConfigRepository",
    "VllmServiceLimitsRecord",
    "default_vllm_deployment_config_repository",
    "effective_vllm_deployment_config",
    "env_vllm_deployment_config",
    "get_vllm_deployment_config_repository",
    "vllm_deployment_config_repository_from_settings",
]
