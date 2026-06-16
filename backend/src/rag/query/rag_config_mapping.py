"""Presentation mapping for RAG runtime configuration."""

from __future__ import annotations

from ..repositories.rag_config import RagConfigRecord
from ..schemas.rag_config import RagConfigHealth, RagConfigResponse


def rag_config_response(record: RagConfigRecord) -> RagConfigResponse:
    return RagConfigResponse(
        source=record.source,
        provider=record.provider,
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
