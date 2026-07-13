"""HTTP request mapping for live RAG runtime configuration."""

from __future__ import annotations

from fastapi import HTTPException, status

from ..core.config import settings
from ..schemas.rag_config import RagConfigRequest, RagModelDiscoveryRequest
from ..shared.contracts.reranker_models import is_supported_reranker_model
from ..shared.fastembed_dense import DEFAULT_FASTEMBED_DENSE_MODEL
from .rag_config_models import RagConfigRecord
from .rag_config_service import RagConfigValidationError
from .rag_config_validation import (
    normalize_inference_base_url,
    normalize_ollama_base_url,
)


def _record_from_request(payload: RagConfigRequest) -> RagConfigRecord:
    provider = _provider(payload.provider)
    reasoning_provider = _role_provider(payload.reasoning_provider, fallback=provider)
    routing_provider = _role_provider(payload.routing_provider, fallback=reasoning_provider)
    faithfulness_provider = _role_provider(payload.faithfulness_provider, fallback=provider)
    ingestion_provider = _role_provider(payload.ingestion_provider, fallback=provider)
    vision_provider = _role_provider(payload.vision_provider, fallback=ingestion_provider)
    embedding_provider = _embedding_provider(payload.embedding_provider, provider=provider)
    base_url = _base_url_from_host_port(payload.host, payload.port, provider=provider)
    embedding_base_url = _embedding_base_url(
        payload.embedding_host,
        payload.embedding_port,
        embedding_provider=embedding_provider,
        fallback=base_url if _embedding_matches_chat_provider(embedding_provider, provider) else "",
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
    reasoning_base_url = _role_base_url(
        payload.reasoning_host,
        payload.reasoning_port,
        fallback=base_url if reasoning_provider == provider else "",
        provider=reasoning_provider,
    )
    routing_base_url = _role_base_url(
        payload.routing_host,
        payload.routing_port,
        fallback=(
            reasoning_base_url
            if routing_provider == reasoning_provider
            else base_url
            if routing_provider == provider
            else ""
        ),
        provider=routing_provider,
    )
    faithfulness_base_url = _role_base_url(
        payload.faithfulness_host,
        payload.faithfulness_port,
        fallback=base_url if faithfulness_provider == provider else "",
        provider=faithfulness_provider,
    )
    ingestion_base_url = _role_base_url(
        payload.ingestion_host,
        payload.ingestion_port,
        fallback=base_url if ingestion_provider == provider else "",
        provider=ingestion_provider,
    )
    vision_base_url = _role_base_url(
        payload.vision_host,
        payload.vision_port,
        fallback=(
            ingestion_base_url
            if vision_provider == ingestion_provider
            else base_url
            if vision_provider == provider
            else ""
        ),
        provider=vision_provider,
    )
    return RagConfigRecord(
        provider=provider,
        embedding_provider=embedding_provider,
        reasoning_provider=reasoning_provider,
        routing_provider=routing_provider,
        faithfulness_provider=faithfulness_provider,
        ingestion_provider=ingestion_provider,
        vision_provider=vision_provider,
        base_url=base_url,
        embedding_base_url=embedding_base_url,
        reasoning_base_url=reasoning_base_url,
        routing_base_url=routing_base_url,
        faithfulness_base_url=faithfulness_base_url,
        ingestion_base_url=ingestion_base_url,
        vision_base_url=vision_base_url,
        chat_model=chat_model,
        embed_model=embed_model,
        faithfulness_model=faithfulness_model or None,
        chat_timeout_seconds=payload.chat_timeout_seconds,
        embed_timeout_seconds=payload.embed_timeout_seconds,
        thinking_enabled=payload.thinking_enabled,
        reasoning_model=reasoning_model or routing_model or None,
        routing_model=routing_model or None,
        ingestion_model=ingestion_model or None,
        vision_model=vision_model or None,
        json_num_predict=payload.json_num_predict,
        retrieval_token_budget=payload.retrieval_token_budget,
        query_planner_enabled=payload.query_planner_enabled,
        reranker_model=reranker_model,
    )


def _model_status_payload(status) -> dict[str, object]:
    return {
        "status": status.status,
        "provider": status.provider,
        "base_url": status.base_url,
        "message": status.message,
        "code": status.code,
    }


def _record_from_discovery_request(payload: RagModelDiscoveryRequest) -> RagConfigRecord:
    provider = _provider(payload.provider)
    reasoning_provider = _role_provider(payload.reasoning_provider, fallback=provider)
    routing_provider = _role_provider(payload.routing_provider, fallback=reasoning_provider)
    faithfulness_provider = _role_provider(payload.faithfulness_provider, fallback=provider)
    ingestion_provider = _role_provider(payload.ingestion_provider, fallback=provider)
    vision_provider = _role_provider(payload.vision_provider, fallback=ingestion_provider)
    embedding_provider = _embedding_provider(payload.embedding_provider, provider=provider)
    base_url = _base_url_from_host_port(payload.host, payload.port, provider=provider)
    reasoning_base_url = _role_base_url(
        payload.reasoning_host,
        payload.reasoning_port,
        fallback=base_url if reasoning_provider == provider else "",
        provider=reasoning_provider,
    )
    routing_base_url = _role_base_url(
        payload.routing_host,
        payload.routing_port,
        fallback=(
            reasoning_base_url
            if routing_provider == reasoning_provider
            else base_url
            if routing_provider == provider
            else ""
        ),
        provider=routing_provider,
    )
    faithfulness_base_url = _role_base_url(
        payload.faithfulness_host,
        payload.faithfulness_port,
        fallback=base_url if faithfulness_provider == provider else "",
        provider=faithfulness_provider,
    )
    ingestion_base_url = _role_base_url(
        payload.ingestion_host,
        payload.ingestion_port,
        fallback=base_url if ingestion_provider == provider else "",
        provider=ingestion_provider,
    )
    vision_base_url = _role_base_url(
        payload.vision_host,
        payload.vision_port,
        fallback=(
            ingestion_base_url
            if vision_provider == ingestion_provider
            else base_url
            if vision_provider == provider
            else ""
        ),
        provider=vision_provider,
    )
    return RagConfigRecord(
        provider=provider,
        embedding_provider=embedding_provider,
        reasoning_provider=reasoning_provider,
        routing_provider=routing_provider,
        faithfulness_provider=faithfulness_provider,
        ingestion_provider=ingestion_provider,
        vision_provider=vision_provider,
        base_url=base_url,
        embedding_base_url=_embedding_base_url(
            payload.embedding_host,
            payload.embedding_port,
            embedding_provider=embedding_provider,
            fallback=base_url if _embedding_matches_chat_provider(embedding_provider, provider) else "",
        ),
        reasoning_base_url=reasoning_base_url,
        routing_base_url=routing_base_url,
        faithfulness_base_url=faithfulness_base_url,
        ingestion_base_url=ingestion_base_url,
        vision_base_url=vision_base_url,
        chat_model="",
        embed_model=DEFAULT_FASTEMBED_DENSE_MODEL if embedding_provider == "fastembed" else "",
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
    if not host:
        if not fallback:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid_inference_endpoint",
                    "message": f"{_provider_display(provider)} role endpoint host is required when it differs from chat.",
                },
            )
        return fallback
    return _base_url_from_host_port(host, port or _default_port(provider), provider=provider)


def _provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in {"ollama", "vllm"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_provider", "message": "Inference provider must be ollama or vllm."},
        )
    return provider


def _embedding_provider(value: str, *, provider: str) -> str:
    _ = provider
    embedding_provider = value.strip().lower()
    if embedding_provider not in {"ollama", "openai_compatible", "fastembed"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_embedding_provider",
                "message": "Embedding provider must be ollama, openai_compatible, or fastembed.",
            },
        )
    return embedding_provider


def _role_provider(value: str | None, *, fallback: str) -> str:
    return _provider(value) if value and value.strip() else fallback


def _embedding_base_url(
    host: str | None,
    port: int | None,
    *,
    embedding_provider: str,
    fallback: str,
) -> str:
    if embedding_provider == "fastembed":
        return fallback
    provider = "vllm" if embedding_provider == "openai_compatible" else "ollama"
    if not host:
        if fallback:
            return fallback
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_embedding_endpoint",
                "message": f"{_embedding_provider_display(embedding_provider)} embedding host is required when it differs from chat.",
            },
        )
    return _base_url_from_host_port(host, port or _default_port(provider), provider=provider)


def _embedding_matches_chat_provider(embedding_provider: str, provider: str) -> bool:
    return (
        embedding_provider == "fastembed"
        or (embedding_provider == "ollama" and provider == "ollama")
        or (embedding_provider == "openai_compatible" and provider == "vllm")
    )


def _default_port(provider: str) -> int:
    return 8000 if provider == "vllm" else 11434


def _provider_display(provider: str) -> str:
    return "vLLM" if provider == "vllm" else "Ollama"


def _embedding_provider_display(value: str) -> str:
    if value == "fastembed":
        return "FastEmbed local"
    if value == "openai_compatible":
        return "OpenAI-compatible"
    return "Ollama"


def _rag_config_http_error(exc: RagConfigValidationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
