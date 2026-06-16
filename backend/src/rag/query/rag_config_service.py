"""Validation and schema helpers for workspace RAG runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from time import perf_counter
from typing import Any

from ..core.config import Settings, settings
from ..repositories.rag_config import RagConfigRecord
from ..shared.contracts.reranker_models import is_supported_reranker_model
from .http import ServiceRequestError, request_json
from .qdrant import QdrantClient


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
    chat_models, embedding_models, role_models = list_runtime_models(config_record)
    _require_model(config_record, "chat", config_record.chat_model, chat_models)
    _require_model(config_record, "reasoning", config_record.effective_reasoning_model, role_models.get("reasoning", chat_models))
    _require_model(config_record, "routing", config_record.routing_model, role_models.get("routing", chat_models))
    _require_model(config_record, "faithfulness", config_record.faithfulness_model, role_models.get("faithfulness", chat_models))
    _require_model(config_record, "ingestion", config_record.ingestion_model, role_models.get("ingestion", chat_models))
    _require_model(config_record, "vision", config_record.vision_model, role_models.get("vision", chat_models))
    if config_record.embed_model not in embedding_models:
        raise RagConfigValidationError(
            code=f"{config_record.provider}_embedding_model_missing",
            message=f"Embedding server is missing required model: {config_record.embed_model}",
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
    embedding_dimension = _embedding_dimension(config_record)
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
        base_url=config_record.base_url,
        embedding_base_url=config_record.embedding_base_url,
        reasoning_base_url=config_record.effective_reasoning_base_url,
        routing_base_url=config_record.effective_routing_base_url,
        faithfulness_base_url=config_record.effective_faithfulness_base_url,
        ingestion_base_url=config_record.effective_ingestion_base_url,
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
        reranker_model=config_record.reranker_model,
        health_status="ok",
        health_message=f"{_provider_label(config_record)} runtime validated successfully.",
        embedding_dimension=result.embedding_dimension,
        chat_latency_ms=result.chat_latency_ms,
        embed_latency_ms=result.embed_latency_ms,
        last_checked_at=result.checked_at,
        updated_by=updated_by,
    )


def list_ollama_models(config_record: RagConfigRecord) -> list[str]:
    try:
        payload = request_json(
            config_record.base_url,
            "/api/tags",
            service="ollama",
            timeout_seconds=config_record.chat_timeout_seconds,
        )
    except ServiceRequestError as exc:
        raise RagConfigValidationError(
            code="ollama_unavailable",
            message=f"Ollama server is unavailable: {exc.message}",
            status_code=503,
        ) from exc
    models = payload.get("models")
    if not isinstance(models, list):
        raise RagConfigValidationError(
            code="ollama_invalid_response",
            message="Ollama tags response did not include a models list.",
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
    if config_record.provider == "ollama":
        models = list_ollama_models(config_record)
        return models, models, {role: models for role in ("reasoning", "routing", "faithfulness", "ingestion", "vision")}
    if config_record.provider == "vllm":
        chat_models = _list_openai_models(config_record.base_url, timeout_seconds=config_record.chat_timeout_seconds, service="vllm")
        model_cache = {config_record.base_url: chat_models}
        role_models: dict[str, list[str]] = {}
        for role, base_url in _role_base_urls(config_record).items():
            if base_url not in model_cache:
                model_cache[base_url] = _list_openai_models(
                    base_url,
                    timeout_seconds=config_record.chat_timeout_seconds,
                    service=f"vllm_{role}",
                )
            role_models[role] = model_cache[base_url]
        return (
            chat_models,
            _list_openai_models(
                config_record.embedding_base_url,
                timeout_seconds=config_record.embed_timeout_seconds,
                service="embeddings",
            ),
            role_models,
        )
    raise RagConfigValidationError(code="invalid_provider", message="Inference provider must be ollama or vllm.")


def _chat_probe(config_record: RagConfigRecord) -> None:
    if config_record.provider == "vllm":
        _openai_chat_probe(config_record)
        return
    try:
        payload = request_json(
            config_record.base_url,
            "/api/chat",
            service="ollama",
            method="POST",
            payload={
                "model": config_record.chat_model,
                "stream": False,
                "think": config_record.thinking_enabled,
                "keep_alive": "5m",
                "format": "json",
                "options": {"temperature": 0, "num_predict": 16},
                "messages": [
                    {"role": "system", "content": "You are a health check endpoint. Return JSON only."},
                    {"role": "user", "content": 'Return {"status":"ok"}.'},
                ],
            },
            timeout_seconds=config_record.chat_timeout_seconds,
        )
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        parsed = json.loads(content) if isinstance(content, str) else None
        if not isinstance(parsed, dict) or parsed.get("status") != "ok":
            raise ServiceRequestError("ollama", "chat health response was invalid", 502)
    except (ServiceRequestError, json.JSONDecodeError) as exc:
        message = exc.message if isinstance(exc, ServiceRequestError) else "chat health response was invalid"
        raise RagConfigValidationError(
            code="ollama_chat_failed",
            message=f"Ollama chat check failed: {message}",
            status_code=503,
        ) from exc


def _role_probe(config_record: RagConfigRecord, role: str, model: str | None) -> None:
    if config_record.provider != "vllm" or not model:
        return
    try:
        _openai_chat_probe(config_record, base_url=_role_base_urls(config_record)[role], model=model, service=f"vllm_{role}")
    except RagConfigValidationError as exc:
        raise RagConfigValidationError(
            code=f"vllm_{role}_chat_failed",
            message=f"vLLM {role} check failed: {exc.message}",
            status_code=exc.status_code,
        ) from exc


def _embedding_dimension(config_record: RagConfigRecord) -> int:
    if config_record.provider == "vllm":
        return _openai_embedding_dimension(config_record)
    try:
        payload = request_json(
            config_record.base_url,
            "/api/embed",
            service="ollama",
            method="POST",
            payload={"model": config_record.embed_model, "input": "AgenticRAG embedding health check."},
            timeout_seconds=config_record.embed_timeout_seconds,
        )
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            return _coerce_dimension(embeddings[0])
    except ServiceRequestError as exc:
        if exc.status_code not in (400, 404):
            raise RagConfigValidationError(
                code="ollama_embedding_failed",
                message=f"Ollama embedding check failed: {exc.message}",
                status_code=503,
            ) from exc

    try:
        payload = request_json(
            config_record.base_url,
            "/api/embeddings",
            service="ollama",
            method="POST",
            payload={"model": config_record.embed_model, "prompt": "AgenticRAG embedding health check."},
            timeout_seconds=config_record.embed_timeout_seconds,
        )
        return _coerce_dimension(payload.get("embedding"))
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


def _coerce_dimension(value: Any) -> int:
    if not isinstance(value, list) or not value:
        raise RagConfigValidationError(
            code="ollama_embedding_failed",
            message="Ollama embedding response did not include a vector.",
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
            return _coerce_dimension(data[0].get("embedding"))
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


def _provider_label(config_record: RagConfigRecord) -> str:
    return "vLLM" if config_record.provider == "vllm" else "Ollama"


def _openai_service_label(service: str) -> str:
    if service == "vllm":
        return "vLLM chat server"
    if service.startswith("vllm_"):
        return f"vLLM {service.removeprefix('vllm_')} server"
    if service == "embeddings":
        return "Embedding server"
    return service.replace("_", " ").capitalize()


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
        raise RagConfigValidationError(
            code=(
                "ollama_model_missing"
                if config_record.provider == "ollama"
                else f"{config_record.provider}_{role}_model_missing"
            ),
            message=f"{_provider_label(config_record)} {role} server is missing required model: {model}",
            status_code=400,
        )


def _role_base_urls(config_record: RagConfigRecord) -> dict[str, str]:
    return {
        "reasoning": config_record.effective_reasoning_base_url,
        "routing": config_record.effective_routing_base_url,
        "faithfulness": config_record.effective_faithfulness_base_url,
        "ingestion": config_record.effective_ingestion_base_url,
    }
