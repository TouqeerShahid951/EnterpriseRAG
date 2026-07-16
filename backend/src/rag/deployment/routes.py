"""Administrator HTTP routes for vLLM deployment configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.dependencies import require_platform_admin_user
from ..auth.identity_models import UserRecord
from .vllm_config_repository import (
    VllmDeploymentConfigRecord,
    VllmDeploymentConfigRepository,
    VllmServiceLimitsRecord,
    effective_vllm_deployment_config,
    get_vllm_deployment_config_repository,
)
from rag.shared.contracts.http import ErrorResponse
from .schemas import (
    VllmDeploymentConfigRequest,
    VllmDeploymentConfigResponse,
    VllmServiceDeploymentLimits,
)
from .application import VllmDeploymentApplyRejected, VllmDeploymentApplyService
from .dependencies import get_vllm_deployment_apply_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/vllm-deployment-config",
    response_model=VllmDeploymentConfigResponse,
    summary="Get desired vLLM container launch limits",
)
def get_vllm_deployment_config(
    user: UserRecord = Depends(require_platform_admin_user),
    repo: VllmDeploymentConfigRepository = Depends(get_vllm_deployment_config_repository),
) -> VllmDeploymentConfigResponse:
    _ = user
    return _vllm_deployment_response(effective_vllm_deployment_config(repo=repo))


@router.put(
    "/vllm-deployment-config",
    response_model=VllmDeploymentConfigResponse,
    summary="Save desired vLLM container launch limits without restarting services",
)
def update_vllm_deployment_config(
    payload: VllmDeploymentConfigRequest,
    user: UserRecord = Depends(require_platform_admin_user),
    repo: VllmDeploymentConfigRepository = Depends(get_vllm_deployment_config_repository),
) -> VllmDeploymentConfigResponse:
    saved = repo.save_active(
        _vllm_record_from_request(
            payload,
            apply_status="restart_required",
            message="Saved. Restart the affected vLLM service when you want it to use these limits.",
            updated_by=user.id,
        )
    )
    return _vllm_deployment_response(saved)


@router.post(
    "/vllm-deployment-config/apply",
    response_model=VllmDeploymentConfigResponse,
    responses={status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse}},
    summary="Apply desired vLLM launch limits and restart allowlisted vLLM services",
)
def apply_vllm_deployment_config(
    payload: VllmDeploymentConfigRequest,
    user: UserRecord = Depends(require_platform_admin_user),
    service: VllmDeploymentApplyService = Depends(get_vllm_deployment_apply_service),
) -> VllmDeploymentConfigResponse:
    try:
        saved = service.apply(
            _vllm_record_from_request(
                payload,
                apply_status="restart_required",
                message=None,
                updated_by=user.id,
            ),
            requested_services=payload.services,
        )
    except VllmDeploymentApplyRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "vllm_deployment_apply_failed",
                "message": exc.message,
            },
        ) from exc
    return _vllm_deployment_response(saved)


def _vllm_record_from_request(
    payload: VllmDeploymentConfigRequest,
    *,
    apply_status: str,
    message: str | None,
    updated_by: str | None,
) -> VllmDeploymentConfigRecord:
    return VllmDeploymentConfigRecord(
        text=_service_limits_record(payload.text),
        embeddings=_service_limits_record(payload.embeddings),
        vision=_service_limits_record(payload.vision),
        apply_status=apply_status,
        message=message,
        updated_by=updated_by,
    )


def _service_limits_record(limits: VllmServiceDeploymentLimits) -> VllmServiceLimitsRecord:
    return VllmServiceLimitsRecord(
        max_model_len=limits.max_model_len,
        gpu_memory_utilization=limits.gpu_memory_utilization,
        kv_cache_memory_bytes=limits.kv_cache_memory_bytes,
        max_num_seqs=limits.max_num_seqs,
        max_num_batched_tokens=limits.max_num_batched_tokens,
    )


def _vllm_deployment_response(record: VllmDeploymentConfigRecord) -> VllmDeploymentConfigResponse:
    return VllmDeploymentConfigResponse(
        source=record.source,
        apply_status=record.apply_status,
        message=record.message,
        text=_service_limits_response(record.text),
        embeddings=_service_limits_response(record.embeddings),
        vision=_service_limits_response(record.vision),
    )


def _service_limits_response(record: VllmServiceLimitsRecord) -> VllmServiceDeploymentLimits:
    return VllmServiceDeploymentLimits(
        max_model_len=record.max_model_len,
        gpu_memory_utilization=record.gpu_memory_utilization,
        kv_cache_memory_bytes=record.kv_cache_memory_bytes,
        max_num_seqs=record.max_num_seqs,
        max_num_batched_tokens=record.max_num_batched_tokens,
    )
