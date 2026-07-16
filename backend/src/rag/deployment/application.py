"""Application workflow for applying desired vLLM deployment limits."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from .vllm_config_models import (
    VllmDeploymentConfigRecord,
    VllmDeploymentConfigRepository,
)


VLLM_DEPLOYMENT_SERVICE_NAMES = {
    "text": "vllm-text",
    "embeddings": "vllm-embeddings",
    "vision": "vllm-vision",
}


class DeploymentControllerError(RuntimeError):
    """The deployment controller could not complete an apply request."""


class DeploymentController(Protocol):
    def apply(
        self,
        record: VllmDeploymentConfigRecord,
        *,
        services: list[str],
    ) -> str: ...


class VllmDeploymentApplyRejected(RuntimeError):
    def __init__(
        self,
        failed_config: VllmDeploymentConfigRecord,
    ) -> None:
        self.failed_config = failed_config
        super().__init__(self.message)

    @property
    def message(self) -> str:
        return self.failed_config.message or "Deployment controller failed."


class VllmDeploymentApplyService:
    """Persist and apply a desired deployment configuration as one workflow."""

    def __init__(
        self,
        *,
        repository: VllmDeploymentConfigRepository,
        controller: DeploymentController,
    ) -> None:
        self._repository = repository
        self._controller = controller

    def apply(
        self,
        desired: VllmDeploymentConfigRecord,
        *,
        requested_services: list[str] | None,
    ) -> VllmDeploymentConfigRecord:
        services = deployment_services(requested_services)
        applying = self._repository.save_active(
            replace(
                desired,
                apply_status="applying",
                message=(
                    "Deployment controller is recreating "
                    f"{deployment_service_message(services)}."
                ),
            )
        )
        try:
            controller_message = self._controller.apply(
                applying,
                services=services,
            )
        except DeploymentControllerError as exc:
            failed = self._repository.save_active(
                replace(
                    desired,
                    apply_status="failed",
                    message=str(exc),
                )
            )
            raise VllmDeploymentApplyRejected(failed) from exc
        return self._repository.save_active(
            replace(
                desired,
                apply_status="applied",
                message=controller_message,
            )
        )


def deployment_services(requested: list[str] | None) -> list[str]:
    service_keys = requested or ["text", "embeddings", "vision"]
    services: list[str] = []
    for key in service_keys:
        service_name = VLLM_DEPLOYMENT_SERVICE_NAMES[key]
        if service_name not in services:
            services.append(service_name)
    return services


def deployment_service_message(services: list[str]) -> str:
    if len(services) == 1:
        return services[0]
    if len(services) == 2:
        return f"{services[0]} and {services[1]}"
    return ", ".join(services[:-1]) + f", and {services[-1]}"
