"""Validation and mapping helpers for workspace RAG configuration records."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from ..core.config import Settings, settings
from .rag_config_models import (
    DEFAULT_OLLAMA_PORT,
    DEFAULT_VLLM_PORT,
    SUPPORTED_INFERENCE_PROVIDERS,
    RagConfigRecord,
)


def normalize_ollama_base_url(host: str, port: int = DEFAULT_OLLAMA_PORT) -> str:
    return normalize_inference_base_url(host, port, provider="ollama")


def normalize_inference_base_url(host: str, port: int, *, provider: str) -> str:
    if provider not in SUPPORTED_INFERENCE_PROVIDERS:
        raise ValueError("Inference provider must be ollama or vllm.")
    raw_host = host.strip()
    if not raw_host:
        raise ValueError("Inference host is required.")
    if not raw_host.startswith(("http://", "https://")):
        raw_host = f"http://{raw_host}"
    parsed = urlsplit(raw_host)
    if parsed.scheme != "http":
        raise ValueError("Only plain HTTP inference endpoints are supported in this local-network mode.")
    if parsed.username or parsed.password:
        raise ValueError("Inference endpoint must not include credentials.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Inference endpoint must be a bare host and optional port.")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError("Inference endpoint port is invalid.") from exc
    selected_port = parsed_port or port
    if selected_port < 1 or selected_port > 65535:
        raise ValueError("Inference endpoint port must be between 1 and 65535.")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Inference endpoint host is invalid.")
    if not _is_allowed_local_network_host(hostname):
        raise ValueError("Inference endpoint must be a private LAN IP, localhost, host.docker.internal, or .local host.")
    return urlunsplit(("http", f"{hostname}:{selected_port}", "", "", ""))


def env_rag_config(config: Settings = settings) -> RagConfigRecord:
    provider = config.rag_model_provider.strip().lower()
    if provider not in SUPPORTED_INFERENCE_PROVIDERS:
        provider = "ollama"
    if provider == "vllm":
        base_url = _normalize_env_base_url(config.vllm_base_url, DEFAULT_VLLM_PORT, provider=provider)
        embedding_base_url = _normalize_env_base_url(config.embeddings_base_url, DEFAULT_VLLM_PORT, provider=provider)
        reasoning_base_url = _normalize_env_base_url(config.vllm_reasoning_base_url or config.vllm_base_url, DEFAULT_VLLM_PORT, provider=provider)
        routing_base_url = _normalize_env_base_url(config.vllm_routing_base_url or config.vllm_reasoning_base_url or config.vllm_base_url, DEFAULT_VLLM_PORT, provider=provider)
        faithfulness_base_url = _normalize_env_base_url(config.vllm_faithfulness_base_url or config.vllm_base_url, DEFAULT_VLLM_PORT, provider=provider)
        ingestion_base_url = _normalize_env_base_url(config.vllm_ingestion_base_url or config.vllm_base_url, DEFAULT_VLLM_PORT, provider=provider)
        chat_model = config.vllm_chat_model
        embed_model = config.embedding_model_id
        thinking_enabled = False
    else:
        base_url = _normalize_env_base_url(config.ollama_base_url, DEFAULT_OLLAMA_PORT, provider=provider)
        embedding_base_url = base_url
        reasoning_base_url = base_url
        routing_base_url = base_url
        faithfulness_base_url = base_url
        ingestion_base_url = base_url
        chat_model = config.ollama_chat_model
        embed_model = config.ollama_embed_model
        thinking_enabled = config.ollama_thinking_enabled
    return RagConfigRecord(
        provider=provider,
        base_url=base_url,
        embedding_base_url=embedding_base_url,
        reasoning_base_url=reasoning_base_url,
        routing_base_url=routing_base_url,
        faithfulness_base_url=faithfulness_base_url,
        ingestion_base_url=ingestion_base_url,
        chat_model=chat_model,
        embed_model=embed_model,
        faithfulness_model=config.rag_faithfulness_model,
        chat_timeout_seconds=config.rag_ollama_chat_timeout_seconds,
        embed_timeout_seconds=config.rag_ollama_embed_timeout_seconds,
        thinking_enabled=thinking_enabled,
        reasoning_model=config.rag_reasoning_model or config.rag_route_llm_verifier_model,
        routing_model=config.rag_route_llm_verifier_model,
        ingestion_model=config.rag_ingestion_model,
        vision_model=config.ollama_vision_model.strip() if provider == "ollama" and config.ollama_vision_model else None,
        json_num_predict=config.rag_json_num_predict,
        retrieval_token_budget=config.rag_retrieval_token_budget,
        reranker_model=config.rag_reranker_model,
        health_status="unknown",
        health_message="Using deployment environment defaults.",
        source="env",
    )


def record_from_row(row: dict[str, object]) -> RagConfigRecord:
    base_url = str(row["base_url"])
    return RagConfigRecord(
        provider=str(row.get("provider") or "ollama"),
        base_url=base_url,
        embedding_base_url=str(row.get("embedding_base_url") or base_url),
        reasoning_base_url=str(row.get("reasoning_base_url") or base_url),
        routing_base_url=str(row.get("routing_base_url") or row.get("reasoning_base_url") or base_url),
        faithfulness_base_url=str(row.get("faithfulness_base_url") or base_url),
        ingestion_base_url=str(row.get("ingestion_base_url") or base_url),
        chat_model=str(row["chat_model"]),
        embed_model=str(row["embed_model"]),
        faithfulness_model=str(row["faithfulness_model"]).strip() if row.get("faithfulness_model") else None,
        chat_timeout_seconds=float(row["chat_timeout_seconds"]),
        embed_timeout_seconds=float(row["embed_timeout_seconds"]),
        thinking_enabled=bool(row.get("thinking_enabled", False)),
        reasoning_model=str(row["reasoning_model"]).strip() if row.get("reasoning_model") else None,
        routing_model=str(row["routing_model"]).strip() if row.get("routing_model") else None,
        ingestion_model=str(row["ingestion_model"]).strip() if row.get("ingestion_model") else None,
        vision_model=str(row["vision_model"]).strip() if row.get("vision_model") else None,
        json_num_predict=int(row.get("json_num_predict") or 4096),
        retrieval_token_budget=int(row.get("retrieval_token_budget") or 12000),
        reranker_model=str(row["reranker_model"]).strip() if row.get("reranker_model") else settings.rag_reranker_model,
        health_status=str(row["health_status"]),
        health_message=str(row["health_message"]),
        embedding_dimension=int(row["embedding_dimension"]) if row.get("embedding_dimension") is not None else None,
        chat_latency_ms=int(row["chat_latency_ms"]) if row.get("chat_latency_ms") is not None else None,
        embed_latency_ms=int(row["embed_latency_ms"]) if row.get("embed_latency_ms") is not None else None,
        last_checked_at=row.get("last_checked_at"),  # type: ignore[arg-type]
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
        updated_at=row.get("updated_at"),  # type: ignore[arg-type]
    )


def with_updated_at(config: RagConfigRecord) -> RagConfigRecord:
    return RagConfigRecord(
        provider=config.provider,
        base_url=config.base_url,
        embedding_base_url=config.embedding_base_url,
        reasoning_base_url=config.effective_reasoning_base_url,
        routing_base_url=config.effective_routing_base_url,
        faithfulness_base_url=config.effective_faithfulness_base_url,
        ingestion_base_url=config.effective_ingestion_base_url,
        chat_model=config.chat_model,
        embed_model=config.embed_model,
        faithfulness_model=config.faithfulness_model,
        chat_timeout_seconds=config.chat_timeout_seconds,
        embed_timeout_seconds=config.embed_timeout_seconds,
        thinking_enabled=config.thinking_enabled,
        reasoning_model=config.reasoning_model,
        routing_model=config.routing_model,
        ingestion_model=config.ingestion_model,
        vision_model=config.vision_model,
        json_num_predict=config.json_num_predict,
        retrieval_token_budget=config.retrieval_token_budget,
        reranker_model=config.reranker_model,
        health_status=config.health_status,
        health_message=config.health_message,
        embedding_dimension=config.embedding_dimension,
        chat_latency_ms=config.chat_latency_ms,
        embed_latency_ms=config.embed_latency_ms,
        last_checked_at=config.last_checked_at,
        updated_by=config.updated_by,
        updated_at=datetime.now(UTC),
    )


def _normalize_env_base_url(value: str, default_port: int, *, provider: str) -> str:
    raw = value.strip().removesuffix("/v1").rstrip("/")
    parsed = urlsplit(raw if raw.startswith(("http://", "https://")) else f"http://{raw}")
    if parsed.scheme != "http" or parsed.username or parsed.password:
        raise ValueError("Deployment inference endpoints must use HTTP without embedded credentials.")
    if not parsed.hostname:
        raise ValueError("Deployment inference endpoint host is invalid.")
    return urlunsplit(("http", f"{parsed.hostname}:{parsed.port or default_port}", "", "", ""))


def _is_allowed_local_network_host(hostname: str) -> bool:
    normalized = hostname.lower()
    if normalized in {"localhost", "host.docker.internal"} or normalized.endswith(".local"):
        return True
    if "." not in normalized and all(character.isalnum() or character == "-" for character in normalized):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return address.is_private or address.is_loopback
