"""Validation and schema helpers for workspace RAG runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from time import perf_counter
from typing import Any

from rag.core.config import Settings, settings
from rag.shared.contracts.reranker_models import is_supported_reranker_model
from rag.shared.fastembed_dense import FastEmbedDenseError, embed_dense_texts, list_supported_dense_models
from rag.shared.ollama_models import is_ollama_cloud_model
from rag.query.http import ServiceRequestError, request_json
from rag.query.qdrant import QdrantClient
from .models import RagConfigRecord
from rag.query.reranker import rank_passages


@dataclass(frozen=True)
class RagConfigValidationResult:
    available_models: list[str]
    embedding_dimension: int
    checked_at: datetime
    embedding_models: list[str] | None = None
    reasoning_models: list[str] | None = None
    routing_models: list[str] | None = None
    faithfulness_models: list[str] | None = None
    ingestion_models: list[str] | None = None
    vision_models: list[str] | None = None
    chat_latency_ms: int = 0
    embed_latency_ms: int = 0

    @property
    def chat_models(self) -> list[str]:
        return self.available_models


@dataclass(frozen=True)
class RuntimeModelDiscoveryStatus:
    status: str
    provider: str
    base_url: str
    message: str
    code: str | None = None


@dataclass(frozen=True)
class RuntimeModelDiscoveryResult:
    chat_models: list[str]
    embedding_models: list[str]
    role_models: dict[str, list[str]]
    statuses: dict[str, RuntimeModelDiscoveryStatus]


class RagConfigValidationError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def validate_rag_config(
    config_record: RagConfigRecord,
    *,
    app_config: Settings = settings,
    qdrant: QdrantClient | None = None,
) -> RagConfigValidationResult:
    if not is_supported_reranker_model(config_record.reranker_model):
        raise RagConfigValidationError(
            code="reranker_model_unsupported",
            message="Selected reranker model is not supported by this workspace.",
        )
    _reranker_probe(config_record, app_config=app_config)
    chat_models, embedding_models, role_models = list_runtime_models(config_record)
    _require_model(config_record, "chat", config_record.chat_model, chat_models)
    _require_model(config_record, "reasoning", config_record.effective_reasoning_model, role_models.get("reasoning", chat_models))
    _require_model(config_record, "routing", config_record.routing_model, role_models.get("routing", chat_models))
    _require_model(config_record, "faithfulness", config_record.faithfulness_model, role_models.get("faithfulness", chat_models))
    _require_model(config_record, "ingestion", config_record.ingestion_model, role_models.get("ingestion", chat_models))
    _require_model(config_record, "vision", config_record.vision_model, role_models.get("vision", chat_models))
    if config_record.embed_model not in embedding_models:
        raise RagConfigValidationError(
            code=f"{config_record.embedding_provider}_embedding_model_missing",
            message=f"{_embedding_provider_label(config_record)} is missing required model: {config_record.embed_model}",
            status_code=400,
        )

    chat_started = perf_counter()
    _chat_probe(config_record)
    _role_probe(config_record, "reasoning", config_record.effective_reasoning_model)
    _role_probe(config_record, "routing", config_record.routing_model)
    _role_probe(config_record, "faithfulness", config_record.faithfulness_model)
    _role_probe(config_record, "ingestion", config_record.ingestion_model)
    chat_latency_ms = max(0, round((perf_counter() - chat_started) * 1000))
    embed_started = perf_counter()
    embedding_dimension = _embedding_dimension(config_record, app_config=app_config)
    embed_latency_ms = max(0, round((perf_counter() - embed_started) * 1000))
    existing_size = _qdrant_vector_size(config_record, app_config=app_config, qdrant=qdrant)
    if existing_size is not None and existing_size != embedding_dimension:
        raise RagConfigValidationError(
            code="embedding_dimension_mismatch",
            message=(
                f"Existing Qdrant collection uses embedding dimension {existing_size}, "
                f"but {config_record.embed_model} returned {embedding_dimension}. Reindex or reset before switching."
            ),
            status_code=409,
        )
    return RagConfigValidationResult(
        available_models=chat_models,
        embedding_models=embedding_models,
        reasoning_models=role_models.get("reasoning"),
        routing_models=role_models.get("routing"),
        faithfulness_models=role_models.get("faithfulness"),
        ingestion_models=role_models.get("ingestion"),
        vision_models=role_models.get("vision"),
        embedding_dimension=embedding_dimension,
        chat_latency_ms=chat_latency_ms,
        embed_latency_ms=embed_latency_ms,
        checked_at=datetime.now(UTC),
    )


def checked_record(
    config_record: RagConfigRecord,
    *,
    result: RagConfigValidationResult,
    updated_by: str | None,
) -> RagConfigRecord:
    return RagConfigRecord(
        provider=config_record.provider,
        embedding_provider=config_record.embedding_provider,
        reasoning_provider=config_record.effective_reasoning_provider,
        routing_provider=config_record.effective_routing_provider,
        faithfulness_provider=config_record.effective_faithfulness_provider,
        ingestion_provider=config_record.effective_ingestion_provider,
        vision_provider=config_record.effective_vision_provider,
        base_url=config_record.base_url,
        embedding_base_url=config_record.embedding_base_url,
        reasoning_base_url=config_record.effective_reasoning_base_url,
        routing_base_url=config_record.effective_routing_base_url,
        faithfulness_base_url=config_record.effective_faithfulness_base_url,
        ingestion_base_url=config_record.effective_ingestion_base_url,
        vision_base_url=config_record.effective_vision_base_url,
        chat_model=config_record.chat_model,
        embed_model=config_record.embed_model,
        faithfulness_model=config_record.faithfulness_model,
        chat_timeout_seconds=config_record.chat_timeout_seconds,
        embed_timeout_seconds=config_record.embed_timeout_seconds,
        thinking_enabled=config_record.thinking_enabled,
        reasoning_model=config_record.reasoning_model,
        routing_model=config_record.routing_model,
        ingestion_model=config_record.ingestion_model,
        vision_model=config_record.vision_model,
        json_num_predict=config_record.json_num_predict,
        retrieval_token_budget=config_record.retrieval_token_budget,
        query_planner_enabled=config_record.query_planner_enabled,
        reranker_model=config_record.reranker_model,
        health_status="ok",
        health_message=(
            "Configured inference roles, reranker, and "
            f"{_embedding_provider_label(config_record)} validated successfully."
        ),
        embedding_dimension=result.embedding_dimension,
        chat_latency_ms=result.chat_latency_ms,
        embed_latency_ms=result.embed_latency_ms,
        last_checked_at=result.checked_at,
        updated_by=updated_by,
    )


def _reranker_probe(
    config_record: RagConfigRecord,
    *,
    app_config: Settings,
) -> None:
    try:
        ranking = rank_passages(
            "reranker inference health check",
            ["reranker inference health check"],
            model_name=config_record.reranker_model,
            cache_dir=app_config.rag_reranker_cache_dir,
        )
        if len(ranking) != 1 or ranking[0][0] != 0:
            raise RuntimeError("reranker probe returned an unexpected result")
    except Exception as exc:
        raise RagConfigValidationError(
            code="reranker_unavailable",
            message=(
                f"Configured reranker {config_record.reranker_model!r} failed its "
                f"inference check: {exc}"
            ),
            status_code=503,
        ) from exc


def _list_ollama_models_at(base_url: str, *, timeout_seconds: float, service: str) -> list[str]:
    try:
        payload = request_json(
            base_url,
            "/api/tags",
            service=service,
            timeout_seconds=timeout_seconds,
        )
    except ServiceRequestError as exc:
        raise RagConfigValidationError(
            code=f"{service}_unavailable",
            message=f"{_provider_service_label(service, 'ollama')} is unavailable: {exc.message}",
            status_code=503,
        ) from exc
    models = payload.get("models")
    if not isinstance(models, list):
        raise RagConfigValidationError(
            code=f"{service}_invalid_response",
            message=f"{_provider_service_label(service, 'ollama')} tags response did not include a models list.",
            status_code=502,
        )
    names = sorted(
        {
            str(model.get("name")).strip()
            for model in models
            if isinstance(model, dict) and str(model.get("name", "")).strip()
        }
    )
    return names


def list_runtime_models(config_record: RagConfigRecord) -> tuple[list[str], list[str], dict[str, list[str]]]:
    chat_models = _list_models_for_provider(
        config_record.provider,
        config_record.base_url,
        timeout_seconds=config_record.chat_timeout_seconds,
        service="chat",
    )
    model_cache: dict[tuple[str, str], list[str]] = {(config_record.provider, config_record.base_url): chat_models}
    role_models: dict[str, list[str]] = {}
    for role, base_url in _role_base_urls(config_record).items():
        provider = config_record.role_provider(role)
        key = (provider, base_url)
        if key not in model_cache:
            model_cache[key] = _list_models_for_provider(
                provider,
                base_url,
                timeout_seconds=config_record.chat_timeout_seconds,
                service=role,
            )
        role_models[role] = model_cache[key]
    return chat_models, _list_embedding_models(config_record), role_models


def discover_runtime_models(config_record: RagConfigRecord) -> RuntimeModelDiscoveryResult:
    statuses: dict[str, RuntimeModelDiscoveryStatus] = {}
    model_cache: dict[tuple[str, str], tuple[list[str], RuntimeModelDiscoveryStatus]] = {}

    def discover_role(role: str, provider: str, base_url: str) -> list[str]:
        key = (provider, base_url)
        if key not in model_cache:
            try:
                models = _list_models_for_provider(
                    provider,
                    base_url,
                    timeout_seconds=config_record.chat_timeout_seconds,
                    service=role,
                )
                status = _discovery_status_from_models(
                    models,
                    provider=provider,
                    base_url=base_url,
                    service=role,
                )
            except RagConfigValidationError as exc:
                models = []
                status = RuntimeModelDiscoveryStatus(
                    status="error",
                    provider=provider,
                    base_url=base_url,
                    code=exc.code,
                    message=exc.message,
                )
            model_cache[key] = (models, status)
        models, status = model_cache[key]
        statuses[role] = status
        return models

    chat_models = discover_role("chat", config_record.provider, config_record.base_url)
    role_models = {
        role: discover_role(role, config_record.role_provider(role), base_url)
        for role, base_url in _role_base_urls(config_record).items()
    }

    try:
        embedding_models = _list_embedding_models(config_record)
        statuses["embedding"] = _discovery_status_from_models(
            embedding_models,
            provider=config_record.embedding_provider,
            base_url=_embedding_status_base_url(config_record),
            service="embedding",
        )
    except RagConfigValidationError as exc:
        embedding_models = []
        statuses["embedding"] = RuntimeModelDiscoveryStatus(
            status="error",
            provider=config_record.embedding_provider,
            base_url=_embedding_status_base_url(config_record),
            code=exc.code,
            message=exc.message,
        )

    return RuntimeModelDiscoveryResult(
        chat_models=chat_models,
        embedding_models=embedding_models,
        role_models=role_models,
        statuses=statuses,
    )


def _chat_probe(config_record: RagConfigRecord) -> None:
    if config_record.provider == "vllm":
        _openai_chat_probe(config_record)
        return
    _ollama_chat_probe(config_record, service="ollama")


def _role_probe(config_record: RagConfigRecord, role: str, model: str | None) -> None:
    if not model:
        return
    provider = config_record.role_provider(role)
    base_url = _role_base_urls(config_record)[role]
    try:
        if provider == "vllm":
            _openai_chat_probe(config_record, base_url=base_url, model=model, service=f"vllm_{role}")
        else:
            _ollama_chat_probe(config_record, base_url=base_url, model=model, service=f"ollama_{role}")
    except RagConfigValidationError as exc:
        raise RagConfigValidationError(
            code=f"{provider}_{role}_chat_failed",
            message=f"{_provider_label(provider)} {role} check failed: {exc.message}",
            status_code=exc.status_code,
        ) from exc


def _list_embedding_models(config_record: RagConfigRecord) -> list[str]:
    if config_record.embedding_provider == "fastembed":
        try:
            return list_supported_dense_models(cache_dir=settings.rag_dense_cache_dir, cached_only=True)
        except FastEmbedDenseError as exc:
            raise RagConfigValidationError(
                code="fastembed_unavailable",
                message=f"FastEmbed dense model discovery failed: {exc}",
                status_code=503,
            ) from exc
    if config_record.embedding_provider == "openai_compatible":
        return _list_openai_models(
            config_record.embedding_base_url,
            timeout_seconds=config_record.embed_timeout_seconds,
            service="embeddings",
        )
    if config_record.embedding_provider == "ollama":
        return _list_ollama_models_at(
            config_record.embedding_base_url,
            timeout_seconds=config_record.embed_timeout_seconds,
            service="ollama_embeddings",
        )
    raise RagConfigValidationError(
        code="invalid_embedding_provider",
        message="Embedding provider must be ollama, openai_compatible, or fastembed.",
    )


def _embedding_dimension(config_record: RagConfigRecord, *, app_config: Settings) -> int:
    if config_record.embedding_provider == "fastembed":
        return _fastembed_embedding_dimension(config_record, app_config=app_config)
    if config_record.embedding_provider == "openai_compatible":
        return _openai_embedding_dimension(config_record)
    try:
        payload = request_json(
            config_record.embedding_base_url,
            "/api/embed",
            service="ollama",
            method="POST",
            payload={"model": config_record.embed_model, "input": "AgenticRAG embedding health check."},
            timeout_seconds=config_record.embed_timeout_seconds,
        )
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            return _coerce_dimension(embeddings[0], provider_label="Ollama")
    except ServiceRequestError as exc:
        if exc.status_code not in (400, 404):
            raise RagConfigValidationError(
                code="ollama_embedding_failed",
                message=f"Ollama embedding check failed: {exc.message}",
                status_code=503,
            ) from exc

    try:
        payload = request_json(
            config_record.embedding_base_url,
            "/api/embeddings",
            service="ollama",
            method="POST",
            payload={"model": config_record.embed_model, "prompt": "AgenticRAG embedding health check."},
            timeout_seconds=config_record.embed_timeout_seconds,
        )
        return _coerce_dimension(payload.get("embedding"), provider_label="Ollama")
    except ServiceRequestError as exc:
        raise RagConfigValidationError(
            code="ollama_embedding_failed",
            message=f"Ollama embedding check failed: {exc.message}",
            status_code=503,
        ) from exc


def _qdrant_vector_size(
    config_record: RagConfigRecord,
    *,
    app_config: Settings,
    qdrant: QdrantClient | None,
) -> int | None:
    client = qdrant or QdrantClient(
        base_url=app_config.qdrant_url,
        collection=app_config.qdrant_collection,
        timeout_seconds=app_config.rag_http_timeout_seconds,
    )
    try:
        return client.current_vector_size()
    except ServiceRequestError as exc:
        raise RagConfigValidationError(
            code="qdrant_unavailable",
            message=f"Qdrant vector schema check failed: {exc.message}",
            status_code=503,
        ) from exc


def _coerce_dimension(value: Any, *, provider_label: str = "Embedding service") -> int:
    if not isinstance(value, list) or not value:
        raise RagConfigValidationError(
            code="embedding_failed",
            message=f"{provider_label} embedding response did not include a vector.",
            status_code=502,
        )
    return len(value)


def _list_openai_models(base_url: str, *, timeout_seconds: float, service: str) -> list[str]:
    path = _openai_path(base_url, "/v1/models")
    try:
        payload = request_json(
            base_url,
            path,
            service=service,
            timeout_seconds=timeout_seconds,
        )
    except ServiceRequestError as exc:
        endpoint = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        raise RagConfigValidationError(
            code=f"{service}_unavailable",
            message=(
                f"{_openai_service_label(service)} model discovery failed at {endpoint}"
                f"{_http_status_suffix(exc)}: {_service_error_detail(exc)}"
            ),
            status_code=503,
        ) from exc
    data = payload.get("data")
    if not isinstance(data, list):
        raise RagConfigValidationError(
            code=f"{service}_invalid_response",
            message=f"{_openai_service_label(service)} models response did not include a data list.",
            status_code=502,
        )
    return sorted(
        {
            str(model.get("id")).strip()
            for model in data
            if isinstance(model, dict) and str(model.get("id", "")).strip()
        }
    )


def _list_models_for_provider(provider: str, base_url: str, *, timeout_seconds: float, service: str) -> list[str]:
    if provider == "ollama":
        return _list_ollama_models_at(base_url, timeout_seconds=timeout_seconds, service=f"ollama_{service}")
    if provider == "vllm":
        return _list_openai_models(base_url, timeout_seconds=timeout_seconds, service=f"vllm_{service}")
    raise RagConfigValidationError(code="invalid_provider", message="Inference provider must be ollama or vllm.")


def _ollama_chat_probe(
    config_record: RagConfigRecord,
    *,
    base_url: str | None = None,
    model: str | None = None,
    service: str = "ollama",
) -> None:
    selected_base_url = base_url or config_record.base_url
    selected_model = model or config_record.chat_model
    request_payload: dict[str, Any] = {
        "model": selected_model,
        "stream": False,
        "think": config_record.thinking_enabled,
        "keep_alive": "5m",
        "options": {"temperature": 0, "num_predict": 16},
        "messages": [
            {"role": "system", "content": "You are a health check endpoint. Return JSON only."},
            {"role": "user", "content": 'Return {"status":"ok"}.'},
        ],
    }
    if not is_ollama_cloud_model(selected_model):
        request_payload["format"] = "json"
    try:
        payload = request_json(
            selected_base_url,
            "/api/chat",
            service=service,
            method="POST",
            payload=request_payload,
            timeout_seconds=config_record.chat_timeout_seconds,
        )
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        parsed = json.loads(content) if isinstance(content, str) else None
        if not isinstance(parsed, dict) or parsed.get("status") != "ok":
            raise ServiceRequestError(service, "chat health response was invalid", 502)
    except (ServiceRequestError, json.JSONDecodeError) as exc:
        message = exc.message if isinstance(exc, ServiceRequestError) else "chat health response was invalid"
        raise RagConfigValidationError(
            code=f"{service}_chat_failed",
            message=message,
            status_code=503,
        ) from exc


def _openai_chat_probe(
    config_record: RagConfigRecord,
    *,
    base_url: str | None = None,
    model: str | None = None,
    service: str = "vllm",
) -> None:
    selected_base_url = base_url or config_record.base_url
    selected_model = model or config_record.chat_model
    try:
        payload = request_json(
            selected_base_url,
            _openai_path(selected_base_url, "/v1/chat/completions"),
            service=service,
            method="POST",
            payload={
                "model": selected_model,
                "stream": False,
                "temperature": 0,
                "max_tokens": 16,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You are a health check endpoint. Return JSON only."},
                    {"role": "user", "content": 'Return {"status":"ok"}.'},
                ],
            },
            timeout_seconds=config_record.chat_timeout_seconds,
        )
        content = _openai_message_content(payload)
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or parsed.get("status") != "ok":
            raise ValueError("invalid health response")
    except (ServiceRequestError, json.JSONDecodeError, ValueError) as exc:
        message = exc.message if isinstance(exc, ServiceRequestError) else "chat health response was invalid"
        raise RagConfigValidationError(
            code=f"{service}_chat_failed",
            message=message,
            status_code=503,
        ) from exc


def _openai_embedding_dimension(config_record: RagConfigRecord) -> int:
    try:
        payload = request_json(
            config_record.embedding_base_url,
            _openai_path(config_record.embedding_base_url, "/v1/embeddings"),
            service="embeddings",
            method="POST",
            payload={"model": config_record.embed_model, "input": ["AgenticRAG embedding health check."]},
            timeout_seconds=config_record.embed_timeout_seconds,
        )
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return _coerce_dimension(data[0].get("embedding"), provider_label="OpenAI-compatible")
    except ServiceRequestError as exc:
        raise RagConfigValidationError(
            code="vllm_embedding_failed",
            message=f"Embedding check failed: {exc.message}",
            status_code=503,
        ) from exc
    raise RagConfigValidationError(
        code="vllm_embedding_failed",
        message="Embedding response did not include a vector.",
        status_code=502,
    )


def _fastembed_embedding_dimension(config_record: RagConfigRecord, *, app_config: Settings) -> int:
    try:
        vectors = embed_dense_texts(
            ["AgenticRAG embedding health check."],
            model_name=config_record.embed_model,
            cache_dir=app_config.rag_dense_cache_dir,
        )
        return _coerce_dimension(vectors[0] if vectors else None, provider_label="FastEmbed")
    except FastEmbedDenseError as exc:
        raise RagConfigValidationError(
            code="fastembed_embedding_failed",
            message=f"FastEmbed embedding check failed: {exc}",
            status_code=503,
        ) from exc


def _openai_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"].strip()
    raise ValueError("chat response did not include message content")


def _openai_path(base_url: str, path: str) -> str:
    if base_url.rstrip("/").endswith("/v1"):
        return path.removeprefix("/v1")
    return path


def _provider_label(value: RagConfigRecord | str) -> str:
    provider = value.provider if isinstance(value, RagConfigRecord) else value
    return "vLLM" if provider == "vllm" else "Ollama"


def _embedding_provider_label(config_record: RagConfigRecord) -> str:
    if config_record.embedding_provider == "fastembed":
        return "FastEmbed local embeddings"
    if config_record.embedding_provider == "openai_compatible":
        return "OpenAI-compatible embedding server"
    return "Ollama embedding server"


def _embedding_status_base_url(config_record: RagConfigRecord) -> str:
    if config_record.embedding_provider == "fastembed":
        return "local FastEmbed cache"
    return config_record.embedding_base_url


def _discovery_status_from_models(
    models: list[str],
    *,
    provider: str,
    base_url: str,
    service: str,
) -> RuntimeModelDiscoveryStatus:
    provider_label = "FastEmbed" if provider == "fastembed" else _provider_label("vllm" if provider == "openai_compatible" else provider)
    if models:
        return RuntimeModelDiscoveryStatus(
            status="ok",
            provider=provider,
            base_url=base_url,
            message=f"{provider_label} {service} returned {len(models)} model{'s' if len(models) != 1 else ''}.",
        )
    return RuntimeModelDiscoveryStatus(
        status="empty",
        provider=provider,
        base_url=base_url,
        message=f"No models returned from {provider_label} {service} at {base_url}.",
        code="no_models",
    )


def _openai_service_label(service: str) -> str:
    if service in {"vllm", "vllm_chat"}:
        return "vLLM chat server"
    if service.startswith("vllm_"):
        return f"vLLM {service.removeprefix('vllm_')} server"
    if service == "embeddings":
        return "Embedding server"
    return service.replace("_", " ").capitalize()


def _provider_service_label(service: str, provider: str) -> str:
    prefix = "Ollama" if provider == "ollama" else "vLLM"
    if service == provider:
        return f"{prefix} server"
    role = service.removeprefix(f"{provider}_").replace("_", " ")
    return f"{prefix} {role} server".strip()


def _http_status_suffix(exc: ServiceRequestError) -> str:
    return f" (HTTP {exc.status_code})" if exc.status_code is not None else ""


def _service_error_detail(exc: ServiceRequestError) -> str:
    try:
        payload = json.loads(exc.message)
    except (json.JSONDecodeError, TypeError):
        return exc.message
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return exc.message


def _require_model(config_record: RagConfigRecord, role: str, model: str | None, models: list[str]) -> None:
    if not model:
        return
    if model not in models:
        provider = config_record.provider if role == "chat" else config_record.role_provider(role)
        raise RagConfigValidationError(
            code=(
                "ollama_model_missing"
                if provider == "ollama"
                else f"{provider}_{role}_model_missing"
            ),
            message=f"{_provider_label(provider)} {role} server is missing required model: {model}",
            status_code=400,
        )


def _role_base_urls(config_record: RagConfigRecord) -> dict[str, str]:
    return {
        "reasoning": config_record.effective_reasoning_base_url,
        "routing": config_record.effective_routing_base_url,
        "faithfulness": config_record.effective_faithfulness_base_url,
        "ingestion": config_record.effective_ingestion_base_url,
        "vision": config_record.effective_vision_base_url,
    }
