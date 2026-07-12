"""Ollama adapter for ingestion metadata and dense embeddings."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Sequence
from typing import Any

from rag.shared.ollama_models import is_ollama_cloud_model

from ..errors import EmbeddingUnavailable
from .http import ServiceRequestError, request_json


METADATA_NUM_PREDICT = 256
METADATA_TIMEOUT_SECONDS = 20.0
METADATA_WARNING = "ollama_metadata_unavailable"
METADATA_TIMEOUT_WARNING = "ollama_metadata_timeout"
METADATA_TRANSPORT_WARNING = "ollama_metadata_transport_error"
METADATA_HTTP_WARNING = "ollama_metadata_http_error"
METADATA_INVALID_JSON_WARNING = "ollama_metadata_invalid_json"
METADATA_FORMAT = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "llm_topics": {"type": "array", "items": {"type": "string"}},
        "doc_type": {
            "type": "string",
            "maxLength": 80,
        },
    },
    "required": ["summary", "llm_topics", "doc_type"],
}


class OllamaClient:
    def __init__(
        self,
        *,
        base_url: str,
        chat_model: str,
        embed_model: str,
        timeout_seconds: float,
        chat_timeout_seconds: float | None = None,
        embed_timeout_seconds: float | None = None,
        thinking_enabled: bool = False,
        retry_base_seconds: float = 0,
        embedding_batch_size: int = 16,
        num_ctx: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.chat_timeout_seconds = chat_timeout_seconds or timeout_seconds
        self.embed_timeout_seconds = embed_timeout_seconds or timeout_seconds
        self.thinking_enabled = thinking_enabled
        self.retry_base_seconds = max(0, retry_base_seconds)
        self.embedding_batch_size = max(1, embedding_batch_size)
        self.num_ctx = num_ctx
        self._sleep = sleep

    def generate_metadata(self, text: str) -> dict[str, Any]:
        prompt = (
            "JSON only: summary, llm_topics, doc_type. "
            "summary=1 factual sentence; llm_topics=3-5 short strings; doc_type=short. "
            f"Text:\n{text[:2000]}"
        )
        request_payload = {
            "model": self.chat_model,
            "stream": False,
            "think": self.thinking_enabled,
            "keep_alive": "5m",
            "options": _ollama_options(
                temperature=0.0,
                num_predict=METADATA_NUM_PREDICT,
                num_ctx=self.num_ctx,
            ),
            "messages": [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        }
        if not is_ollama_cloud_model(self.chat_model):
            request_payload["format"] = METADATA_FORMAT
        last_error: ServiceRequestError | None = None
        last_attempt = 0
        for attempt in range(1):
            last_attempt = attempt + 1
            try:
                payload = request_json(
                    self.base_url,
                    "/api/chat",
                    service="ollama",
                    method="POST",
                    payload=request_payload,
                    timeout_seconds=min(self.chat_timeout_seconds, METADATA_TIMEOUT_SECONDS),
                )
                parsed = _parse_json_object(_message_content(payload))
                if not isinstance(parsed, dict):
                    raise ServiceRequestError("ollama", "metadata response was not a JSON object", 502)
                return _coerce_metadata(parsed)
            except ServiceRequestError as exc:
                last_error = exc
                if attempt >= 2 or not is_transient_service_error(exc):
                    break
                self._backoff(attempt)
        warning = _metadata_warning_for_error(last_error)
        return _metadata_fallback(
            warning=warning,
            error=_metadata_error_payload(last_error, warning=warning, attempts=last_attempt) if last_error else None,
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def generate_json(self, *, prompt: str, model: str | None = None, system: str) -> str:
        selected_model = model or self.chat_model
        request_payload = {
            "model": selected_model,
            "stream": False,
            "think": self.thinking_enabled,
            "keep_alive": "5m",
            "options": _ollama_options(
                temperature=0.0,
                num_predict=4096,
                num_ctx=self.num_ctx,
            ),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if not is_ollama_cloud_model(selected_model):
            request_payload["format"] = "json"
        last_error: ServiceRequestError | None = None
        for attempt in range(3):
            try:
                payload = request_json(
                    self.base_url,
                    "/api/chat",
                    service="ollama",
                    method="POST",
                    payload=request_payload,
                    timeout_seconds=self.chat_timeout_seconds,
                )
                return _message_content(payload)
            except ServiceRequestError as exc:
                last_error = exc
                if attempt >= 2 or not is_transient_service_error(exc):
                    break
                self._backoff(attempt)
        raise last_error or ServiceRequestError("ollama", "JSON generation request failed", 502)

    def embed_many(
        self,
        texts: Sequence[str],
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        expected_dimension: int | None = None
        for offset in range(0, len(texts), self.embedding_batch_size):
            batch = list(texts[offset : offset + self.embedding_batch_size])
            batch_vectors = self._embed_batch(batch, expected_dimension=expected_dimension)
            for vector in batch_vectors:
                if expected_dimension is None:
                    expected_dimension = len(vector)
                elif len(vector) != expected_dimension:
                    raise EmbeddingUnavailable("Ollama returned inconsistent embedding dimensions.")
            vectors.extend(batch_vectors)
            if progress is not None:
                progress(len(vectors), len(texts))
        return vectors

    def _embed_batch(self, texts: list[str], *, expected_dimension: int | None) -> list[list[float]]:
        last_error: ServiceRequestError | None = None
        for attempt in range(3):
            try:
                payload = request_json(
                    self.base_url,
                    "/api/embed",
                    service="ollama",
                    method="POST",
                    payload={"model": self.embed_model, "input": texts, "keep_alive": "5m"},
                    timeout_seconds=self.embed_timeout_seconds,
                )
                vectors = _coerce_embedding_batch(payload.get("embeddings"), expected_count=len(texts))
                if expected_dimension is not None and any(len(vector) != expected_dimension for vector in vectors):
                    raise ServiceRequestError("ollama", "embedding dimensions changed between batches", 502)
                return vectors
            except ServiceRequestError as exc:
                last_error = exc
                if not is_transient_service_error(exc):
                    raise
                if attempt >= 2:
                    break
                self._backoff(attempt)
        message = last_error.message if last_error else "embedding request failed"
        raise EmbeddingUnavailable(message[:500])

    def _backoff(self, attempt: int) -> None:
        delay = self.retry_base_seconds * (2**attempt)
        if delay:
            self._sleep(delay)


def is_transient_service_error(exc: ServiceRequestError) -> bool:
    return exc.status_code is None or exc.status_code in {408, 429} or (
        exc.status_code is not None and 500 <= exc.status_code <= 599
    )


def metadata_timeout_seconds(chat_timeout_seconds: float) -> float:
    return min(chat_timeout_seconds, METADATA_TIMEOUT_SECONDS)


def _ollama_options(*, temperature: float, num_predict: int, num_ctx: int | None) -> dict[str, int | float]:
    options: dict[str, int | float] = {"temperature": temperature, "num_predict": num_predict}
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    return options


def _message_content(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"].strip()
    if isinstance(payload.get("response"), str):
        return payload["response"].strip()
    raise ServiceRequestError("ollama", "chat response did not include content", 502)


def _parse_json_object(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ServiceRequestError("ollama", "metadata response was not valid JSON", 502)
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ServiceRequestError("ollama", "metadata response was not valid JSON", 502) from exc


def _coerce_metadata(value: dict[str, Any]) -> dict[str, Any]:
    topics = value.get("topics")
    normalized_topics = [str(item).strip() for item in topics if str(item).strip()] if isinstance(topics, list) else []
    doc_type = " ".join(str(value.get("doc_type", "")).strip().lower().split())[:80]
    return {
        "summary": str(value.get("summary", "")).strip(),
        "topics": normalized_topics[:5],
        "llm_topics": _coerce_topics(value.get("llm_topics") or topics)[:8],
        "doc_type": doc_type,
        "claims": _coerce_claims(value.get("claims")),
    }


def _metadata_fallback(
    *,
    warning: str = METADATA_WARNING,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = {
        "summary": "",
        "topics": [],
        "llm_topics": [],
        "doc_type": "",
        "claims": [],
        "_warnings": [warning],
    }
    if error:
        fallback["_metadata_errors"] = [error]
    return fallback


def _metadata_warning_for_error(exc: ServiceRequestError | None) -> str:
    if exc is None:
        return METADATA_WARNING
    message = exc.message.lower()
    if "timed out" in message or "timeout" in message:
        return METADATA_TIMEOUT_WARNING
    if "json" in message or "did not include content" in message:
        return METADATA_INVALID_JSON_WARNING
    if exc.status_code is not None:
        return METADATA_HTTP_WARNING
    return METADATA_TRANSPORT_WARNING


def _metadata_error_payload(
    exc: ServiceRequestError,
    *,
    warning: str,
    attempts: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "warning": warning,
        "service": exc.service,
        "attempts": max(1, attempts),
        "message": _safe_metadata_error_message(exc, warning),
    }
    if exc.status_code is not None:
        payload["status_code"] = exc.status_code
    return payload


def _safe_metadata_error_message(exc: ServiceRequestError, warning: str) -> str:
    if warning == METADATA_TIMEOUT_WARNING:
        return "request timed out"
    if warning == METADATA_INVALID_JSON_WARNING:
        return "metadata response was not valid JSON"
    if warning == METADATA_HTTP_WARNING and exc.status_code is not None:
        return f"metadata service returned HTTP {exc.status_code}"
    if warning == METADATA_TRANSPORT_WARNING:
        return "metadata transport error"
    return "metadata request failed"


def _coerce_topics(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def _coerce_claims(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    claims: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity", "")).strip()
        attribute = str(item.get("attribute", "")).strip()
        claim_value = str(item.get("value", "")).strip()
        if entity and attribute and claim_value:
            claims.append({"entity": entity, "attribute": attribute, "value": claim_value})
    return claims[:20]


def _coerce_embedding_batch(value: Any, *, expected_count: int) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != expected_count:
        raise ServiceRequestError("ollama", "embedding response vector count did not match the request", 502)
    vectors = [_coerce_vector(vector) for vector in value]
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise ServiceRequestError("ollama", "embedding response contained inconsistent dimensions", 502)
    return vectors


def _coerce_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ServiceRequestError("ollama", "embedding response did not include a vector", 502)
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ServiceRequestError("ollama", "embedding vector contained non-numeric values", 502) from exc
    if not all(math.isfinite(item) for item in vector):
        raise ServiceRequestError("ollama", "embedding vector contained non-finite values", 502)
    return vector
