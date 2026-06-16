"""Persistent desired vLLM container deployment limits."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol

from ..core.config import Settings, settings
from .postgres import PostgresConnectionMixin

ACTIVE_CONFIG_KEY = "active"


@dataclass(frozen=True)
class VllmServiceLimitsRecord:
    max_model_len: int
    gpu_memory_utilization: float
    max_num_seqs: int
    max_num_batched_tokens: int
    kv_cache_memory_bytes: str | None = None


@dataclass(frozen=True)
class VllmDeploymentConfigRecord:
    text: VllmServiceLimitsRecord
    embeddings: VllmServiceLimitsRecord
    vision: VllmServiceLimitsRecord
    apply_status: str = "restart_required"
    message: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None
    source: str = "workspace"


class VllmDeploymentConfigRepository(Protocol):
    def get_active(self) -> VllmDeploymentConfigRecord | None: ...
    def save_active(self, config: VllmDeploymentConfigRecord) -> VllmDeploymentConfigRecord: ...


class InMemoryVllmDeploymentConfigRepository:
    def __init__(self) -> None:
        self.active: VllmDeploymentConfigRecord | None = None

    def get_active(self) -> VllmDeploymentConfigRecord | None:
        return self.active

    def save_active(self, config: VllmDeploymentConfigRecord) -> VllmDeploymentConfigRecord:
        self.active = replace(config, updated_at=datetime.now(UTC))
        return self.active


class PostgresVllmDeploymentConfigRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_active(self) -> VllmDeploymentConfigRecord | None:
        self._ensure_table()
        row = self._execute_optional("SELECT * FROM workspace_vllm_deployment_config WHERE config_key = %s", (ACTIVE_CONFIG_KEY,))
        return _record_from_row(row) if row else None

    def save_active(self, config: VllmDeploymentConfigRecord) -> VllmDeploymentConfigRecord:
        self._ensure_table()
        row = self._execute_one(
            """
            INSERT INTO workspace_vllm_deployment_config (
                config_key, apply_status, message,
                text_max_model_len, text_gpu_memory_utilization, text_kv_cache_memory_bytes,
                text_max_num_seqs, text_max_num_batched_tokens,
                embed_max_model_len, embed_gpu_memory_utilization,
                embed_max_num_seqs, embed_max_num_batched_tokens,
                vision_max_model_len, vision_gpu_memory_utilization, vision_kv_cache_memory_bytes,
                vision_max_num_seqs, vision_max_num_batched_tokens,
                updated_by
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s::uuid
            )
            ON CONFLICT (config_key) DO UPDATE SET
                apply_status = EXCLUDED.apply_status,
                message = EXCLUDED.message,
                text_max_model_len = EXCLUDED.text_max_model_len,
                text_gpu_memory_utilization = EXCLUDED.text_gpu_memory_utilization,
                text_kv_cache_memory_bytes = EXCLUDED.text_kv_cache_memory_bytes,
                text_max_num_seqs = EXCLUDED.text_max_num_seqs,
                text_max_num_batched_tokens = EXCLUDED.text_max_num_batched_tokens,
                embed_max_model_len = EXCLUDED.embed_max_model_len,
                embed_gpu_memory_utilization = EXCLUDED.embed_gpu_memory_utilization,
                embed_max_num_seqs = EXCLUDED.embed_max_num_seqs,
                embed_max_num_batched_tokens = EXCLUDED.embed_max_num_batched_tokens,
                vision_max_model_len = EXCLUDED.vision_max_model_len,
                vision_gpu_memory_utilization = EXCLUDED.vision_gpu_memory_utilization,
                vision_kv_cache_memory_bytes = EXCLUDED.vision_kv_cache_memory_bytes,
                vision_max_num_seqs = EXCLUDED.vision_max_num_seqs,
                vision_max_num_batched_tokens = EXCLUDED.vision_max_num_batched_tokens,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            RETURNING *
            """,
            (
                ACTIVE_CONFIG_KEY,
                config.apply_status,
                config.message,
                config.text.max_model_len,
                config.text.gpu_memory_utilization,
                config.text.kv_cache_memory_bytes,
                config.text.max_num_seqs,
                config.text.max_num_batched_tokens,
                config.embeddings.max_model_len,
                config.embeddings.gpu_memory_utilization,
                config.embeddings.max_num_seqs,
                config.embeddings.max_num_batched_tokens,
                config.vision.max_model_len,
                config.vision.gpu_memory_utilization,
                config.vision.kv_cache_memory_bytes,
                config.vision.max_num_seqs,
                config.vision.max_num_batched_tokens,
                config.updated_by,
            ),
        )
        return _record_from_row(row)

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_vllm_deployment_config (
                    config_key TEXT PRIMARY KEY DEFAULT 'active',
                    apply_status TEXT NOT NULL DEFAULT 'restart_required',
                    message TEXT NULL,
                    text_max_model_len INTEGER NOT NULL,
                    text_gpu_memory_utilization DOUBLE PRECISION NOT NULL,
                    text_kv_cache_memory_bytes TEXT NULL,
                    text_max_num_seqs INTEGER NOT NULL,
                    text_max_num_batched_tokens INTEGER NOT NULL,
                    embed_max_model_len INTEGER NOT NULL,
                    embed_gpu_memory_utilization DOUBLE PRECISION NOT NULL,
                    embed_max_num_seqs INTEGER NOT NULL,
                    embed_max_num_batched_tokens INTEGER NOT NULL,
                    vision_max_model_len INTEGER NOT NULL,
                    vision_gpu_memory_utilization DOUBLE PRECISION NOT NULL,
                    vision_kv_cache_memory_bytes TEXT NULL,
                    vision_max_num_seqs INTEGER NOT NULL,
                    vision_max_num_batched_tokens INTEGER NOT NULL,
                    updated_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT workspace_vllm_deployment_config_singleton CHECK (config_key = 'active'),
                    CONSTRAINT workspace_vllm_deployment_config_status CHECK (
                        apply_status IN ('restart_required', 'applying', 'applied', 'failed')
                    ),
                    CONSTRAINT workspace_vllm_deployment_config_positive_lengths CHECK (
                        text_max_model_len BETWEEN 256 AND 262144 AND
                        embed_max_model_len BETWEEN 256 AND 262144 AND
                        vision_max_model_len BETWEEN 256 AND 262144
                    ),
                    CONSTRAINT workspace_vllm_deployment_config_gpu_utilization CHECK (
                        text_gpu_memory_utilization > 0 AND text_gpu_memory_utilization <= 1 AND
                        embed_gpu_memory_utilization > 0 AND embed_gpu_memory_utilization <= 1 AND
                        vision_gpu_memory_utilization > 0 AND vision_gpu_memory_utilization <= 1
                    )
                )
                """
            )


def effective_vllm_deployment_config(
    *,
    config: Settings = settings,
    repo: VllmDeploymentConfigRepository | None = None,
) -> VllmDeploymentConfigRecord:
    repository = repo or vllm_deployment_config_repository_from_settings(config)
    return repository.get_active() or env_vllm_deployment_config(config)


def env_vllm_deployment_config(config: Settings = settings) -> VllmDeploymentConfigRecord:
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


def vllm_deployment_config_repository_from_settings(config: Settings) -> VllmDeploymentConfigRepository:
    if config.document_repository == "memory":
        return InMemoryVllmDeploymentConfigRepository()
    return PostgresVllmDeploymentConfigRepository(config.database_url)


@lru_cache
def default_vllm_deployment_config_repository() -> VllmDeploymentConfigRepository:
    return vllm_deployment_config_repository_from_settings(settings)


def get_vllm_deployment_config_repository() -> VllmDeploymentConfigRepository:
    return default_vllm_deployment_config_repository()


def _record_from_row(row: dict[str, object]) -> VllmDeploymentConfigRecord:
    return VllmDeploymentConfigRecord(
        text=VllmServiceLimitsRecord(
            max_model_len=int(row["text_max_model_len"]),
            gpu_memory_utilization=float(row["text_gpu_memory_utilization"]),
            kv_cache_memory_bytes=str(row["text_kv_cache_memory_bytes"]) if row.get("text_kv_cache_memory_bytes") else None,
            max_num_seqs=int(row["text_max_num_seqs"]),
            max_num_batched_tokens=int(row["text_max_num_batched_tokens"]),
        ),
        embeddings=VllmServiceLimitsRecord(
            max_model_len=int(row["embed_max_model_len"]),
            gpu_memory_utilization=float(row["embed_gpu_memory_utilization"]),
            max_num_seqs=int(row["embed_max_num_seqs"]),
            max_num_batched_tokens=int(row["embed_max_num_batched_tokens"]),
        ),
        vision=VllmServiceLimitsRecord(
            max_model_len=int(row["vision_max_model_len"]),
            gpu_memory_utilization=float(row["vision_gpu_memory_utilization"]),
            kv_cache_memory_bytes=str(row["vision_kv_cache_memory_bytes"]) if row.get("vision_kv_cache_memory_bytes") else None,
            max_num_seqs=int(row["vision_max_num_seqs"]),
            max_num_batched_tokens=int(row["vision_max_num_batched_tokens"]),
        ),
        apply_status=str(row["apply_status"]),
        message=str(row["message"]) if row.get("message") else None,
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
        updated_at=row.get("updated_at"),  # type: ignore[arg-type]
    )
