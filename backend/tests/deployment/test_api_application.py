"""API-side deployment application workflow tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from rag.deployment.application import (
    DeploymentControllerError,
    VllmDeploymentApplyRejected,
    VllmDeploymentApplyService,
)
from rag.query.adapters.vllm_config_memory import (
    InMemoryVllmDeploymentConfigRepository,
)
from rag.query.vllm_config_models import VllmDeploymentConfigRecord
from rag.query.vllm_config_repository import env_vllm_deployment_config


class RecordingController:
    def __init__(self, *, error: DeploymentControllerError | None = None) -> None:
        self.error = error
        self.calls: list[tuple[VllmDeploymentConfigRecord, list[str]]] = []

    def apply(
        self,
        record: VllmDeploymentConfigRecord,
        *,
        services: list[str],
    ) -> str:
        self.calls.append((record, services))
        if self.error:
            raise self.error
        return "Controller applied the requested limits."


def test_apply_persists_applying_then_applied_state() -> None:
    repository = InMemoryVllmDeploymentConfigRepository()
    controller = RecordingController()
    desired = replace(
        env_vllm_deployment_config(),
        source="workspace",
        updated_by="admin-1",
    )

    saved = VllmDeploymentApplyService(
        repository=repository,
        controller=controller,
    ).apply(desired, requested_services=["text", "vision", "text"])

    applying, services = controller.calls[0]
    assert applying.apply_status == "applying"
    assert applying.message == (
        "Deployment controller is recreating vllm-text and vllm-vision."
    )
    assert services == ["vllm-text", "vllm-vision"]
    assert saved.apply_status == "applied"
    assert saved.message == "Controller applied the requested limits."
    assert saved.updated_by == "admin-1"
    assert repository.get_active() == saved


def test_controller_failure_persists_failed_state_before_rejection() -> None:
    repository = InMemoryVllmDeploymentConfigRepository()
    controller = RecordingController(
        error=DeploymentControllerError("controller refused the operation")
    )
    desired = replace(
        env_vllm_deployment_config(),
        source="workspace",
        updated_by="admin-2",
    )

    with pytest.raises(VllmDeploymentApplyRejected) as captured:
        VllmDeploymentApplyService(
            repository=repository,
            controller=controller,
        ).apply(desired, requested_services=["embeddings"])

    failed = repository.get_active()
    assert failed is not None
    assert failed.apply_status == "failed"
    assert failed.message == "controller refused the operation"
    assert failed.updated_by == "admin-2"
    assert captured.value.failed_config == failed
    assert captured.value.message == "controller refused the operation"
