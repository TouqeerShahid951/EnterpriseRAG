"""Validation and mapping helpers for workspace RAG configuration records."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from rag.core.config import Settings, settings
from rag.shared.contracts.rag_defaults import DEFAULT_MODEL_PROVIDER
from .models import (
    DEFAULT_OLLAMA_PORT,
    DEFAULT_VLLM_PORT,
    SUPPORTED_EMBEDDING_PROVIDERS,
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
    provider = _env_provider(
        config.rag_chat_provider or config.rag_model_provider,
        default=DEFAULT_MODEL_PROVIDER,
    )
    reasoning_provider = _env_provider(config.rag_reasoning_provider, default=provider)
    routing_provider = _env_provider(config.rag_routing_provider, default=reasoning_provider)
    faithfulness_provider = _env_provider(config.rag_faithfulness_provider, default=provider)
    ingestion_provider = _env_provider(config.rag_ingestion_provider, default=provider)
    vision_provider = _env_provider(config.rag_vision_provider, default=ingestion_provider)
    embedding_provider = config.rag_embedding_provider.strip().lower()
    if embedding_provider not in SUPPORTED_EMBEDDING_PROVIDERS:
        allowed = ", ".join(sorted(SUPPORTED_EMBEDDING_PROVIDERS))
        raise ValueError(
            f"RAG_EMBEDDING_PROVIDER must be one of {allowed}; got {embedding_provider!r}"
        )
    base_url = _role_env_base_url(config.rag_chat_base_url, provider=provider, role="chat", config=config)
    embedding_base_url = _embedding_env_base_url(embedding_provider, fallback=base_url, config=config)
    reasoning_base_url = _role_env_base_url(
        config.rag_reasoning_base_url,
        provider=reasoning_provider,
        role="reasoning",
        config=config,
    )
    routing_base_url = _role_env_base_url(
        config.rag_routing_base_url,
        provider=routing_provider,
        role="routing",
        config=config,
        legacy_fallback=config.vllm_routing_base_url or config.vllm_reasoning_base_url,
    )
    faithfulness_base_url = _role_env_base_url(
        config.rag_faithfulness_base_url,
        provider=faithfulness_provider,
        role="faithfulness",
        config=config,
    )
    ingestion_base_url = _role_env_base_url(
        config.rag_ingestion_base_url,
        provider=ingestion_provider,
        role="ingestion",
        config=config,
    )
    vision_base_url = _role_env_base_url(
        config.rag_vision_base_url,
        provider=vision_provider,
        role="vision",
        config=config,
    )
    chat_model = (config.rag_chat_model or _default_chat_model(provider, config)).strip()
    embed_model = _default_embedding_model(embedding_provider, config)
    vision_model = (
        config.rag_vision_model
        or (config.ollama_vision_model if vision_provider == "ollama" else config.vllm_vision_model_id)
        or ""
    ).strip()
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
        faithfulness_model=config.rag_faithfulness_model,
        chat_timeout_seconds=config.rag_ollama_chat_timeout_seconds,
        embed_timeout_seconds=config.rag_ollama_embed_timeout_seconds,
        thinking_enabled=config.ollama_thinking_enabled,
        reasoning_model=config.rag_reasoning_model or config.rag_route_llm_verifier_model,
        routing_model=config.rag_route_llm_verifier_model,
        ingestion_model=config.rag_ingestion_model,
        vision_model=vision_model or None,
        json_num_predict=config.rag_json_num_predict,
        retrieval_token_budget=config.rag_retrieval_token_budget,
        query_planner_enabled=config.rag_query_planner_enabled,
        reranker_model=config.rag_reranker_model,
        health_status="unknown",
        health_message="Using deployment environment defaults.",
        source="env",
    )


def record_from_row(row: dict[str, object]) -> RagConfigRecord:
    base_url = str(row["base_url"])
    return RagConfigRecord(
        provider=str(row.get("provider") or "ollama"),
        embedding_provider=str(row.get("embedding_provider") or ""),
        reasoning_provider=str(row.get("reasoning_provider") or row.get("provider") or "ollama"),
        routing_provider=str(row.get("routing_provider") or row.get("reasoning_provider") or row.get("provider") or "ollama"),
        faithfulness_provider=str(row.get("faithfulness_provider") or row.get("provider") or "ollama"),
        ingestion_provider=str(row.get("ingestion_provider") or row.get("provider") or "ollama"),
        vision_provider=str(row.get("vision_provider") or row.get("ingestion_provider") or row.get("provider") or "ollama"),
        base_url=base_url,
        embedding_base_url=str(row.get("embedding_base_url") or base_url),
        reasoning_base_url=str(row.get("reasoning_base_url") or base_url),
        routing_base_url=str(row.get("routing_base_url") or row.get("reasoning_base_url") or base_url),
        faithfulness_base_url=str(row.get("faithfulness_base_url") or base_url),
        ingestion_base_url=str(row.get("ingestion_base_url") or base_url),
        vision_base_url=str(row.get("vision_base_url") or row.get("ingestion_base_url") or base_url),
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
        query_planner_enabled=bool(
            row["query_planner_enabled"] if row.get("query_planner_enabled") is not None else True
        ),
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
        embedding_provider=config.embedding_provider,
        reasoning_provider=config.effective_reasoning_provider,
        routing_provider=config.effective_routing_provider,
        faithfulness_provider=config.effective_faithfulness_provider,
        ingestion_provider=config.effective_ingestion_provider,
        vision_provider=config.effective_vision_provider,
        base_url=config.base_url,
        embedding_base_url=config.embedding_base_url,
        reasoning_base_url=config.effective_reasoning_base_url,
        routing_base_url=config.effective_routing_base_url,
        faithfulness_base_url=config.effective_faithfulness_base_url,
        ingestion_base_url=config.effective_ingestion_base_url,
        vision_base_url=config.effective_vision_base_url,
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
        query_planner_enabled=config.query_planner_enabled,
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


def _env_provider(value: str | None, *, default: str) -> str:
    provider = (value or default).strip().lower()
    if provider not in SUPPORTED_INFERENCE_PROVIDERS:
        allowed = ", ".join(sorted(SUPPORTED_INFERENCE_PROVIDERS))
        raise ValueError(
            f"RAG inference provider must be one of {allowed}; got {provider!r}"
        )
    return provider


def _role_env_base_url(
    value: str | None,
    *,
    provider: str,
    role: str,
    config: Settings,
    legacy_fallback: str | None = None,
) -> str:
    selected = (value or legacy_fallback or _default_base_url(provider, role=role, config=config)).strip()
    return _normalize_env_base_url(selected, _default_port(provider), provider=provider)


def _embedding_env_base_url(embedding_provider: str, *, fallback: str, config: Settings) -> str:
    if embedding_provider == "fastembed":
        return fallback
    if embedding_provider == "openai_compatible":
        return _normalize_env_base_url(config.embeddings_base_url, DEFAULT_VLLM_PORT, provider="vllm")
    return _normalize_env_base_url(config.ollama_base_url, DEFAULT_OLLAMA_PORT, provider="ollama")


def _default_base_url(provider: str, *, role: str, config: Settings) -> str:
    if provider == "ollama":
        return config.ollama_base_url
    if role == "reasoning":
        return config.vllm_reasoning_base_url or config.vllm_base_url
    if role == "routing":
        return config.vllm_routing_base_url or config.vllm_reasoning_base_url or config.vllm_base_url
    if role == "faithfulness":
        return config.vllm_faithfulness_base_url or config.vllm_base_url
    if role == "ingestion":
        return config.vllm_ingestion_base_url or config.vllm_base_url
    if role == "vision":
        return config.vllm_vision_base_url or config.vllm_base_url
    return config.vllm_base_url


def _default_chat_model(provider: str, config: Settings) -> str:
    return config.vllm_chat_model if provider == "vllm" else config.ollama_chat_model


def _default_embedding_model(embedding_provider: str, config: Settings) -> str:
    if embedding_provider == "fastembed":
        return config.rag_fastembed_model
    if embedding_provider == "openai_compatible":
        return config.embedding_model_id
    return config.ollama_embed_model


def _default_port(provider: str) -> int:
    return DEFAULT_VLLM_PORT if provider == "vllm" else DEFAULT_OLLAMA_PORT


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
