"""Admin RAG runtime configuration routes."""

from __future__ import annotations

import json
from urllib import error as urlerror
from urllib import request as urlrequest

from fastapi import APIRouter, Depends, HTTPException, status

from ...auth.dependencies import require_platform_admin_user
from ...core.config import settings
from ...repositories.identity import UserRecord
from ...repositories.rag_config import (
    RagConfigRecord,
    RagConfigRepository,
    effective_rag_config,
    get_rag_config_repository,
    normalize_inference_base_url,
    normalize_ollama_base_url,
)
from ...repositories.vllm_deployment_config import (
    VllmDeploymentConfigRecord,
    VllmDeploymentConfigRepository,
    VllmServiceLimitsRecord,
    effective_vllm_deployment_config,
    get_vllm_deployment_config_repository,
)
from ...query.rag_config_mapping import rag_config_response
from ...query.rag_config_service import (
    RagConfigValidationError,
    checked_record,
    list_ollama_models,
    list_runtime_models,
    validate_rag_config,
)
from ...schemas.common import ErrorResponse
from ...schemas.rag_config import (
    RagConfigHealth,
    RagConfigRequest,
    RagConfigResponse,
    RagConfigTestResponse,
    RagModelDiscoveryRequest,
    RagModelDiscoveryResponse,
    RerankerModelOption,
    RerankerModelsResponse,
    VllmDeploymentConfigRequest,
    VllmDeploymentConfigResponse,
    VllmServiceDeploymentLimits,
)
from ...shared.contracts.reranker_models import DEFAULT_RERANKER_MODEL, SUPPORTED_RERANKER_MODELS, is_supported_reranker_model

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/rag-config", response_model=RagConfigResponse, summary="Get workspace RAG model runtime config")
def get_workspace_rag_config(
    user: UserRecord = Depends(require_platform_admin_user),
    repo: RagConfigRepository = Depends(get_rag_config_repository),
) -> RagConfigResponse:
    _ = user
    return rag_config_response(effective_rag_config(repo=repo))


@router.get(
    "/rag-config/rerankers",
    response_model=RerankerModelsResponse,
    summary="List supported local cross-encoder reranker models",
)
def list_workspace_reranker_models(
    user: UserRecord = Depends(require_platform_admin_user),
) -> RerankerModelsResponse:
    _ = user
    return RerankerModelsResponse(
        models=[
            RerankerModelOption(model=model, default=model == DEFAULT_RERANKER_MODEL)
            for model in SUPPORTED_RERANKER_MODELS
        ]
    )


@router.post(
    "/rag-config/models",
    response_model=RagModelDiscoveryResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    summary="List models from candidate workspace inference runtimes",
)
def list_workspace_rag_models(
    payload: RagModelDiscoveryRequest,
    user: UserRecord = Depends(require_platform_admin_user),
) -> RagModelDiscoveryResponse:
    _ = user
    candidate = _record_from_discovery_request(payload)
    try:
        if candidate.provider == "ollama":
            chat_models = list_ollama_models(candidate)
            embedding_models = chat_models
            role_models = {role: chat_models for role in ("reasoning", "routing", "faithfulness", "ingestion", "vision")}
        else:
            chat_models, embedding_models, role_models = list_runtime_models(candidate)
    except RagConfigValidationError as exc:
        raise _rag_config_http_error(exc) from exc
    return RagModelDiscoveryResponse(
        provider=candidate.provider,
        base_url=candidate.base_url,
        embedding_base_url=candidate.embedding_base_url,
        reasoning_base_url=candidate.effective_reasoning_base_url,
        routing_base_url=candidate.effective_routing_base_url,
        faithfulness_base_url=candidate.effective_faithfulness_base_url,
        ingestion_base_url=candidate.effective_ingestion_base_url,
        chat_models=chat_models,
        embedding_models=embedding_models,
        reasoning_models=role_models["reasoning"],
        routing_models=role_models["routing"],
        faithfulness_models=role_models["faithfulness"],
        ingestion_models=role_models["ingestion"],
        vision_models=role_models.get("vision", chat_models),
        available_models=chat_models,
    )


@router.post(
    "/rag-config/test",
    response_model=RagConfigTestResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    summary="Test a candidate workspace inference runtime config",
)
def test_workspace_rag_config(
    payload: RagConfigRequest,
    user: UserRecord = Depends(require_platform_admin_user),
) -> RagConfigTestResponse:
    _ = user
    candidate = _record_from_request(payload)
    try:
        result = validate_rag_config(candidate, app_config=settings)
    except RagConfigValidationError as exc:
        raise _rag_config_http_error(exc) from exc
    return RagConfigTestResponse(
        provider=candidate.provider,
        base_url=candidate.base_url,
        embedding_base_url=candidate.embedding_base_url,
        reasoning_base_url=candidate.effective_reasoning_base_url,
        routing_base_url=candidate.effective_routing_base_url,
        faithfulness_base_url=candidate.effective_faithfulness_base_url,
        ingestion_base_url=candidate.effective_ingestion_base_url,
        chat_models=result.chat_models,
        embedding_models=result.embedding_models or result.chat_models,
        reasoning_models=result.reasoning_models or result.chat_models,
        routing_models=result.routing_models or result.chat_models,
        faithfulness_models=result.faithfulness_models or result.chat_models,
        ingestion_models=result.ingestion_models or result.chat_models,
        vision_models=result.vision_models or result.chat_models,
        available_models=result.chat_models,
        thinking_enabled=candidate.thinking_enabled,
        json_num_predict=candidate.json_num_predict,
        retrieval_token_budget=candidate.retrieval_token_budget,
        reranker_model=candidate.reranker_model,
        health=RagConfigHealth(
            status="ok",
            message=f"{'vLLM' if candidate.provider == 'vllm' else 'Ollama'} runtime validated successfully.",
            embedding_dimension=result.embedding_dimension,
            chat_latency_ms=result.chat_latency_ms,
            embed_latency_ms=result.embed_latency_ms,
            checked_at=result.checked_at,
        ),
    )


@router.put(
    "/rag-config",
    response_model=RagConfigResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    summary="Save the active workspace inference runtime config",
)
def update_workspace_rag_config(
    payload: RagConfigRequest,
    user: UserRecord = Depends(require_platform_admin_user),
    repo: RagConfigRepository = Depends(get_rag_config_repository),
) -> RagConfigResponse:
    candidate = _record_from_request(payload)
    try:
        result = validate_rag_config(candidate, app_config=settings)
    except RagConfigValidationError as exc:
        raise _rag_config_http_error(exc) from exc
    saved = repo.save_active(checked_record(candidate, result=result, updated_by=user.id))
    return rag_config_response(saved)


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
            message="Saved. Apply restart to recreate the vLLM containers with these limits.",
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
    repo: VllmDeploymentConfigRepository = Depends(get_vllm_deployment_config_repository),
) -> VllmDeploymentConfigResponse:
    applying = repo.save_active(
        _vllm_record_from_request(
            payload,
            apply_status="applying",
            message="Deployment controller is recreating the vLLM containers.",
            updated_by=user.id,
        )
    )
    try:
        controller_message = _call_deployment_controller(applying)
    except RuntimeError as exc:
        failed = repo.save_active(
            _vllm_record_from_request(
                payload,
                apply_status="failed",
                message=str(exc),
                updated_by=user.id,
            )
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "vllm_deployment_apply_failed", "message": failed.message},
        ) from exc
    saved = repo.save_active(
        _vllm_record_from_request(
            payload,
            apply_status="applied",
            message=controller_message,
            updated_by=user.id,
        )
    )
    return _vllm_deployment_response(saved)


def _record_from_request(payload: RagConfigRequest) -> RagConfigRecord:
    provider = _provider(payload.provider)
    base_url = _base_url_from_host_port(payload.host, payload.port, provider=provider)
    embedding_base_url = (
        base_url
        if provider == "ollama"
        else _base_url_from_host_port(
            payload.embedding_host or "",
            payload.embedding_port or 8000,
            provider=provider,
        )
    )
    chat_model = payload.chat_model.strip()
    embed_model = payload.embed_model.strip()
    if not chat_model or not embed_model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_inference_models", "message": "Chat and embedding models are required."},
        )
    faithfulness_model = payload.faithfulness_model.strip() if payload.faithfulness_model else None
    reasoning_model = payload.reasoning_model.strip() if payload.reasoning_model else None
    routing_model = payload.routing_model.strip() if payload.routing_model else None
    ingestion_model = payload.ingestion_model.strip() if payload.ingestion_model else None
    vision_model = payload.vision_model.strip() if payload.vision_model else None
    reranker_model = payload.reranker_model.strip()
    if not is_supported_reranker_model(reranker_model):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "reranker_model_unsupported",
                "message": "Selected reranker model is not supported by this workspace.",
            },
        )
    return RagConfigRecord(
        provider=provider,
        base_url=base_url,
        embedding_base_url=embedding_base_url,
        reasoning_base_url=_role_base_url(payload.reasoning_host, payload.reasoning_port, fallback=base_url, provider=provider),
        routing_base_url=_role_base_url(
            payload.routing_host,
            payload.routing_port,
            fallback=_role_base_url(payload.reasoning_host, payload.reasoning_port, fallback=base_url, provider=provider),
            provider=provider,
        ),
        faithfulness_base_url=_role_base_url(payload.faithfulness_host, payload.faithfulness_port, fallback=base_url, provider=provider),
        ingestion_base_url=_role_base_url(payload.ingestion_host, payload.ingestion_port, fallback=base_url, provider=provider),
        chat_model=chat_model,
        embed_model=embed_model,
        faithfulness_model=faithfulness_model or None,
        chat_timeout_seconds=payload.chat_timeout_seconds,
        embed_timeout_seconds=payload.embed_timeout_seconds,
        thinking_enabled=payload.thinking_enabled if provider == "ollama" else False,
        reasoning_model=reasoning_model or routing_model or None,
        routing_model=routing_model or None,
        ingestion_model=ingestion_model or None,
        vision_model=vision_model or None,
        json_num_predict=payload.json_num_predict,
        retrieval_token_budget=payload.retrieval_token_budget,
        reranker_model=reranker_model,
    )


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


def _call_deployment_controller(record: VllmDeploymentConfigRecord) -> str:
    url = settings.deployment_controller_url.rstrip("/") + "/v1/vllm/apply"
    request = urlrequest.Request(
        url,
        data=json.dumps(_deployment_controller_payload(record)).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            settings.service_token_header: settings.service_token,
        },
    )
    try:
        with urlrequest.urlopen(request, timeout=settings.deployment_controller_timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Deployment controller returned {exc.code}: {_truncate(error_body)}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Deployment controller is unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Deployment controller timed out while applying vLLM limits.") from exc

    try:
        parsed = json.loads(body or "{}")
    except json.JSONDecodeError:
        return "vLLM services were recreated; controller returned a non-JSON response."
    message = parsed.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "vLLM services were recreated with the saved deployment limits."


def _deployment_controller_payload(record: VllmDeploymentConfigRecord) -> dict[str, object]:
    return {
        "services": ["vllm-text", "vllm-embeddings", "vllm-vision"],
        "text": _service_limits_payload(record.text),
        "embeddings": _service_limits_payload(record.embeddings),
        "vision": _service_limits_payload(record.vision),
    }


def _service_limits_payload(record: VllmServiceLimitsRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "max_model_len": record.max_model_len,
        "gpu_memory_utilization": record.gpu_memory_utilization,
        "max_num_seqs": record.max_num_seqs,
        "max_num_batched_tokens": record.max_num_batched_tokens,
    }
    if record.kv_cache_memory_bytes:
        payload["kv_cache_memory_bytes"] = record.kv_cache_memory_bytes
    return payload


def _truncate(value: str, limit: int = 1200) -> str:
    clean = value.strip()
    return clean if len(clean) <= limit else f"{clean[:limit]}..."


def _record_from_discovery_request(payload: RagModelDiscoveryRequest) -> RagConfigRecord:
    provider = _provider(payload.provider)
    base_url = _base_url_from_host_port(payload.host, payload.port, provider=provider)
    return RagConfigRecord(
        provider=provider,
        base_url=base_url,
        embedding_base_url=(
            base_url
            if provider == "ollama"
            else _base_url_from_host_port(
                payload.embedding_host or "",
                payload.embedding_port or 8000,
                provider=provider,
            )
        ),
        reasoning_base_url=_role_base_url(payload.reasoning_host, payload.reasoning_port, fallback=base_url, provider=provider),
        routing_base_url=_role_base_url(
            payload.routing_host,
            payload.routing_port,
            fallback=_role_base_url(payload.reasoning_host, payload.reasoning_port, fallback=base_url, provider=provider),
            provider=provider,
        ),
        faithfulness_base_url=_role_base_url(payload.faithfulness_host, payload.faithfulness_port, fallback=base_url, provider=provider),
        ingestion_base_url=_role_base_url(payload.ingestion_host, payload.ingestion_port, fallback=base_url, provider=provider),
        chat_model="",
        embed_model="",
        faithfulness_model=None,
        chat_timeout_seconds=payload.timeout_seconds,
        embed_timeout_seconds=payload.timeout_seconds,
        thinking_enabled=False,
        reasoning_model=None,
        routing_model=None,
        ingestion_model=None,
        vision_model=None,
        json_num_predict=settings.rag_json_num_predict,
        retrieval_token_budget=settings.rag_retrieval_token_budget,
    )


def _base_url_from_host_port(host: str, port: int, *, provider: str) -> str:
    try:
        if provider == "ollama":
            return normalize_ollama_base_url(host, port)
        return normalize_inference_base_url(host, port, provider=provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_inference_endpoint", "message": str(exc)},
        ) from exc


def _role_base_url(host: str | None, port: int | None, *, fallback: str, provider: str) -> str:
    if provider == "ollama" or not host:
        return fallback
    return _base_url_from_host_port(host, port or 8000, provider=provider)


def _provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in {"ollama", "vllm"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_provider", "message": "Inference provider must be ollama or vllm."},
        )
    return provider


def _rag_config_http_error(exc: RagConfigValidationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
