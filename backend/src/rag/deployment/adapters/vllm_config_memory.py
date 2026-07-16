"""In-memory adapter for desired vLLM deployment limits."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from ..vllm_config_models import VllmDeploymentConfigRecord


class InMemoryVllmDeploymentConfigRepository:
    def __init__(self) -> None:
        self.active: VllmDeploymentConfigRecord | None = None

    def get_active(self) -> VllmDeploymentConfigRecord | None:
        return self.active

    def save_active(
        self,
        config: VllmDeploymentConfigRecord,
    ) -> VllmDeploymentConfigRecord:
        self.active = replace(config, updated_at=datetime.now(UTC))
        return self.active
