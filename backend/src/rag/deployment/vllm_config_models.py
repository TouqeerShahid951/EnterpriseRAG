"""vLLM deployment configuration records and repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


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

    def save_active(
        self,
        config: VllmDeploymentConfigRecord,
    ) -> VllmDeploymentConfigRecord: ...
