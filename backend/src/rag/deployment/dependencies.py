"""Composition providers for deployment-control application services."""

from fastapi import Depends

from ..core.config import settings
from .vllm_config_models import VllmDeploymentConfigRepository
from .vllm_config_repository import (
    get_vllm_deployment_config_repository,
)
from .application import (
    DeploymentController,
    VllmDeploymentApplyService,
)
from .controller_client import HttpDeploymentControllerClient


def get_deployment_controller() -> DeploymentController:
    return HttpDeploymentControllerClient(
        base_url=settings.deployment_controller_url,
        token=settings.deployment_controller_token,
        timeout_seconds=settings.deployment_controller_timeout_seconds,
    )


def get_vllm_deployment_apply_service(
    repository: VllmDeploymentConfigRepository = Depends(
        get_vllm_deployment_config_repository
    ),
    controller: DeploymentController = Depends(get_deployment_controller),
) -> VllmDeploymentApplyService:
    return VllmDeploymentApplyService(
        repository=repository,
        controller=controller,
    )
