"""Administrator HTTP routes for live RAG runtime configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from rag.auth.dependencies import require_platform_admin_user
from rag.auth.identity_models import UserRecord
from rag.core.config import settings
from .http_mapping import (
    _embedding_provider_display,
    _model_status_payload,
    _rag_config_http_error,
    _record_from_discovery_request,
    _record_from_request,
)
from .repository import (
    RagConfigRepository,
    effective_rag_config,
    env_rag_config,
    get_rag_config_repository,
)
from .mapping import rag_config_response
from .service import (
    RagConfigValidationError,
    checked_record,
    discover_runtime_models,
    validate_rag_config,
)
from rag.shared.contracts.http import ErrorResponse
from rag.query.configuration.schemas import (
    RagConfigHealth,
    RagConfigRequest,
    RagConfigResponse,
    RagConfigTestResponse,
    RagModelDiscoveryRequest,
    RagModelDiscoveryResponse,
    RerankerModelOption,
    RerankerModelsResponse,
)
from rag.shared.contracts.reranker_models import (
    DEFAULT_RERANKER_MODEL,
    SUPPORTED_RERANKER_MODELS,
)
from rag.shared.fastembed_cache import (
    RERANKER_REQUIRED_SNAPSHOT_FILES,
    has_complete_fastembed_model_cache,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/rag-config", response_model=RagConfigResponse, summary="Get workspace RAG model runtime config")
def get_workspace_rag_config(
    user: UserRecord = Depends(require_platform_admin_user),
    repo: RagConfigRepository = Depends(get_rag_config_repository),
) -> RagConfigResponse:
    _ = user
    return rag_config_response(effective_rag_config(repo=repo))


@router.delete(
    "/rag-config",
    response_model=RagConfigResponse,
    summary="Restore the deployment environment RAG runtime config",
)
def reset_workspace_rag_config(
    user: UserRecord = Depends(require_platform_admin_user),
    repo: RagConfigRepository = Depends(get_rag_config_repository),
) -> RagConfigResponse:
    _ = user
    fallback = rag_config_response(env_rag_config(settings))
    repo.delete_active()
    return fallback


@router.get(
    "/rag-config/rerankers",
    response_model=RerankerModelsResponse,
    summary="List cached local cross-encoder reranker models",
)
def list_workspace_reranker_models(
    user: UserRecord = Depends(require_platform_admin_user),
) -> RerankerModelsResponse:
    _ = user
    return RerankerModelsResponse(
        models=[
            RerankerModelOption(model=model, default=model == DEFAULT_RERANKER_MODEL)
            for model in SUPPORTED_RERANKER_MODELS
            if has_complete_fastembed_model_cache(
                settings.rag_reranker_cache_dir,
                model,
                required_files=RERANKER_REQUIRED_SNAPSHOT_FILES,
            )
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
    discovery = discover_runtime_models(candidate)
    return RagModelDiscoveryResponse(
        provider=candidate.provider,
        embedding_provider=candidate.embedding_provider,
        reasoning_provider=candidate.effective_reasoning_provider,
        routing_provider=candidate.effective_routing_provider,
        faithfulness_provider=candidate.effective_faithfulness_provider,
        ingestion_provider=candidate.effective_ingestion_provider,
        vision_provider=candidate.effective_vision_provider,
        base_url=candidate.base_url,
        embedding_base_url=candidate.embedding_base_url,
        reasoning_base_url=candidate.effective_reasoning_base_url,
        routing_base_url=candidate.effective_routing_base_url,
        faithfulness_base_url=candidate.effective_faithfulness_base_url,
        ingestion_base_url=candidate.effective_ingestion_base_url,
        vision_base_url=candidate.effective_vision_base_url,
        chat_models=discovery.chat_models,
        embedding_models=discovery.embedding_models,
        reasoning_models=discovery.role_models["reasoning"],
        routing_models=discovery.role_models["routing"],
        faithfulness_models=discovery.role_models["faithfulness"],
        ingestion_models=discovery.role_models["ingestion"],
        vision_models=discovery.role_models.get("vision", discovery.chat_models),
        available_models=discovery.chat_models,
        model_statuses={key: _model_status_payload(status) for key, status in discovery.statuses.items()},
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
        embedding_provider=candidate.embedding_provider,
        reasoning_provider=candidate.effective_reasoning_provider,
        routing_provider=candidate.effective_routing_provider,
        faithfulness_provider=candidate.effective_faithfulness_provider,
        ingestion_provider=candidate.effective_ingestion_provider,
        vision_provider=candidate.effective_vision_provider,
        base_url=candidate.base_url,
        embedding_base_url=candidate.embedding_base_url,
        reasoning_base_url=candidate.effective_reasoning_base_url,
        routing_base_url=candidate.effective_routing_base_url,
        faithfulness_base_url=candidate.effective_faithfulness_base_url,
        ingestion_base_url=candidate.effective_ingestion_base_url,
        vision_base_url=candidate.effective_vision_base_url,
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
        query_planner_enabled=candidate.query_planner_enabled,
        evidence_gate_policy=candidate.evidence_gate_policy,
        faithfulness_policy=candidate.faithfulness_policy,
        reranker_model=candidate.reranker_model,
        health=RagConfigHealth(
            status="ok",
            message=(
                "Configured inference roles, reranker, and "
                f"{_embedding_provider_display(candidate.embedding_provider)} embeddings validated successfully."
            ),
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
