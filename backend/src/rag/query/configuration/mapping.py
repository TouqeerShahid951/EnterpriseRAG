"""Presentation mapping for RAG runtime configuration."""

from __future__ import annotations

from typing import Any

from rag.shared.contracts.reranker_models import is_supported_reranker_model
from .models import (
    SUPPORTED_EMBEDDING_PROVIDERS,
    SUPPORTED_INFERENCE_PROVIDERS,
    RagConfigRecord,
)
from rag.query.configuration.schemas import RagConfigHealth, RagConfigResponse


def rag_config_response(record: RagConfigRecord) -> RagConfigResponse:
    return RagConfigResponse(
        source=record.source,
        provider=record.provider,
        embedding_provider=record.embedding_provider,
        reasoning_provider=record.effective_reasoning_provider,
        routing_provider=record.effective_routing_provider,
        faithfulness_provider=record.effective_faithfulness_provider,
        ingestion_provider=record.effective_ingestion_provider,
        vision_provider=record.effective_vision_provider,
        base_url=record.base_url,
        host=record.host,
        port=record.port,
        embedding_base_url=record.embedding_base_url,
        embedding_host=record.embedding_host,
        embedding_port=record.embedding_port,
        reasoning_base_url=record.effective_reasoning_base_url,
        reasoning_host=record.role_host("reasoning"),
        reasoning_port=record.role_port("reasoning"),
        routing_base_url=record.effective_routing_base_url,
        routing_host=record.role_host("routing"),
        routing_port=record.role_port("routing"),
        faithfulness_base_url=record.effective_faithfulness_base_url,
        faithfulness_host=record.role_host("faithfulness"),
        faithfulness_port=record.role_port("faithfulness"),
        ingestion_base_url=record.effective_ingestion_base_url,
        ingestion_host=record.role_host("ingestion"),
        ingestion_port=record.role_port("ingestion"),
        vision_base_url=record.effective_vision_base_url,
        vision_host=record.role_host("vision"),
        vision_port=record.role_port("vision"),
        chat_model=record.chat_model,
        embed_model=record.embed_model,
        reasoning_model=record.effective_reasoning_model,
        routing_model=record.routing_model,
        faithfulness_model=record.faithfulness_model,
        ingestion_model=record.ingestion_model,
        vision_model=record.vision_model,
        reranker_model=record.reranker_model,
        thinking_enabled=record.thinking_enabled,
        json_num_predict=record.json_num_predict,
        retrieval_token_budget=record.retrieval_token_budget,
        query_planner_enabled=record.query_planner_enabled,
        chat_timeout_seconds=record.chat_timeout_seconds,
        embed_timeout_seconds=record.embed_timeout_seconds,
        health=RagConfigHealth(
            status=record.health_status,
            message=record.health_message,
            embedding_dimension=record.embedding_dimension,
            chat_latency_ms=record.chat_latency_ms,
            embed_latency_ms=record.embed_latency_ms,
            checked_at=record.last_checked_at,
        ),
    )


def rag_config_from_snapshot(snapshot: dict[str, Any]) -> RagConfigRecord:
    """Reconstruct a resolved runtime config without consulting live state."""

    if not snapshot:
        raise ValueError("RAG configuration snapshot is empty")
    response = RagConfigResponse.model_validate(snapshot)
    provider = _inference_provider(response.provider, field="provider")
    reasoning_provider = _optional_inference_provider(
        response.reasoning_provider, fallback=provider, field="reasoning_provider"
    )
    routing_provider = _optional_inference_provider(
        response.routing_provider,
        fallback=reasoning_provider,
        field="routing_provider",
    )
    faithfulness_provider = _optional_inference_provider(
        response.faithfulness_provider,
        fallback=provider,
        field="faithfulness_provider",
    )
    ingestion_provider = _optional_inference_provider(
        response.ingestion_provider,
        fallback=provider,
        field="ingestion_provider",
    )
    vision_provider = _optional_inference_provider(
        response.vision_provider,
        fallback=ingestion_provider,
        field="vision_provider",
    )
    embedding_provider = response.embedding_provider.strip().lower()
    if embedding_provider not in SUPPORTED_EMBEDDING_PROVIDERS:
        raise ValueError("RAG configuration snapshot has an unsupported embedding provider")
    if not is_supported_reranker_model(response.reranker_model):
        raise ValueError("RAG configuration snapshot has an unsupported reranker model")
    if response.chat_timeout_seconds <= 0 or response.embed_timeout_seconds <= 0:
        raise ValueError("RAG configuration snapshot timeouts must be positive")
    if not 256 <= response.json_num_predict <= 32768:
        raise ValueError("RAG configuration snapshot JSON token limit is invalid")
    if not 1000 <= response.retrieval_token_budget <= 200000:
        raise ValueError("RAG configuration snapshot retrieval token budget is invalid")

    return RagConfigRecord(
        source=_required_text(response.source, field="source"),
        provider=provider,
        embedding_provider=embedding_provider,
        reasoning_provider=reasoning_provider,
        routing_provider=routing_provider,
        faithfulness_provider=faithfulness_provider,
        ingestion_provider=ingestion_provider,
        vision_provider=vision_provider,
        base_url=_required_text(response.base_url, field="base_url"),
        embedding_base_url=_required_text(
            response.embedding_base_url, field="embedding_base_url"
        ),
        reasoning_base_url=_required_text(
            response.reasoning_base_url or response.base_url,
            field="reasoning_base_url",
        ),
        routing_base_url=_required_text(
            response.routing_base_url
            or response.reasoning_base_url
            or response.base_url,
            field="routing_base_url",
        ),
        faithfulness_base_url=_required_text(
            response.faithfulness_base_url or response.base_url,
            field="faithfulness_base_url",
        ),
        ingestion_base_url=_required_text(
            response.ingestion_base_url or response.base_url,
            field="ingestion_base_url",
        ),
        vision_base_url=_required_text(
            response.vision_base_url
            or response.ingestion_base_url
            or response.base_url,
            field="vision_base_url",
        ),
        chat_model=_required_text(response.chat_model, field="chat_model"),
        embed_model=_required_text(response.embed_model, field="embed_model"),
        reasoning_model=_optional_text(response.reasoning_model),
        routing_model=_optional_text(response.routing_model),
        faithfulness_model=_optional_text(response.faithfulness_model),
        ingestion_model=_optional_text(response.ingestion_model),
        vision_model=_optional_text(response.vision_model),
        thinking_enabled=response.thinking_enabled,
        json_num_predict=response.json_num_predict,
        retrieval_token_budget=response.retrieval_token_budget,
        query_planner_enabled=response.query_planner_enabled,
        reranker_model=response.reranker_model,
        chat_timeout_seconds=response.chat_timeout_seconds,
        embed_timeout_seconds=response.embed_timeout_seconds,
        health_status=response.health.status,
        health_message=response.health.message,
        embedding_dimension=response.health.embedding_dimension,
        chat_latency_ms=response.health.chat_latency_ms,
        embed_latency_ms=response.health.embed_latency_ms,
        last_checked_at=response.health.checked_at,
    )


def _inference_provider(value: str, *, field: str) -> str:
    provider = value.strip().lower()
    if provider not in SUPPORTED_INFERENCE_PROVIDERS:
        raise ValueError(f"RAG configuration snapshot has an unsupported {field}")
    return provider


def _optional_inference_provider(
    value: str | None, *, fallback: str, field: str
) -> str:
    return _inference_provider(value or fallback, field=field)


def _required_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"RAG configuration snapshot {field} is blank")
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None
