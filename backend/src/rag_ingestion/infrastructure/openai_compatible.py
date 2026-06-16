"""OpenAI-compatible ingestion metadata and embedding adapter."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Sequence
from typing import Any

from rag.shared.thinking import (
    no_thinking_payload_fields,
    no_thinking_prompt,
    no_thinking_system,
    strip_thinking_content,
)

from ..errors import OllamaEmbeddingUnavailable
from .http import ServiceRequestError, request_json
from .ollama import METADATA_NUM_PREDICT, _coerce_metadata, _metadata_fallback, is_transient_service_error


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        embedding_base_url: str,
        chat_model: str,
        embed_model: str,
        timeout_seconds: float,
        chat_timeout_seconds: float | None = None,
        embed_timeout_seconds: float | None = None,
        retry_base_seconds: float = 0,
        embedding_batch_size: int = 16,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url
        self.embedding_base_url = embedding_base_url
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.chat_timeout_seconds = chat_timeout_seconds or timeout_seconds
        self.embed_timeout_seconds = embed_timeout_seconds or timeout_seconds
        self.retry_base_seconds = max(0, retry_base_seconds)
        self.embedding_batch_size = max(1, embedding_batch_size)
        self._sleep = sleep

    def generate_metadata(self, text: str) -> dict[str, Any]:
        prompt = (
            "Extract compact factual metadata from the document. "
            "The summary must be exactly two factual sentences. "
            "Return JSON with summary, llm_topics, doc_type, and claims.\n\n"
            f"Document text:\n{text[:6000]}"
        )
        for attempt in range(3):
            try:
                payload = request_json(
                    self.base_url,
                    _openai_path(self.base_url, "/v1/chat/completions"),
                    service="vllm",
                    method="POST",
                    payload={
                        "model": self.chat_model,
                        "stream": False,
                        "temperature": 0,
                        "max_tokens": METADATA_NUM_PREDICT,
                        "response_format": {"type": "json_object"},
                        **no_thinking_payload_fields(),
                        "messages": [
                            {"role": "system", "content": no_thinking_system("You extract compact document metadata.")},
                            {"role": "user", "content": no_thinking_prompt(prompt, self.chat_model)},
                        ],
                    },
                    timeout_seconds=self.chat_timeout_seconds,
                )
                parsed = json.loads(_message_content(payload))
                if not isinstance(parsed, dict):
                    raise ServiceRequestError("vllm", "metadata response was not a JSON object", 502)
                return _coerce_metadata(parsed)
            except (ServiceRequestError, json.JSONDecodeError) as exc:
                service_error = exc if isinstance(exc, ServiceRequestError) else ServiceRequestError("vllm", str(exc), 502)
                if attempt >= 2 or not is_transient_service_error(service_error):
                    break
                self._backoff(attempt)
        return _metadata_fallback()

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

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
            batch_vectors = self._embed_batch(batch)
            for vector in batch_vectors:
                if expected_dimension is None:
                    expected_dimension = len(vector)
                elif len(vector) != expected_dimension:
                    raise OllamaEmbeddingUnavailable("Embedding service returned inconsistent dimensions.")
            vectors.extend(batch_vectors)
            if progress is not None:
                progress(len(vectors), len(texts))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        last_error: ServiceRequestError | None = None
        for attempt in range(3):
            try:
                payload = request_json(
                    self.embedding_base_url,
                    _openai_path(self.embedding_base_url, "/v1/embeddings"),
                    service="embeddings",
                    method="POST",
                    payload={"model": self.embed_model, "input": texts},
                    timeout_seconds=self.embed_timeout_seconds,
                )
                data = payload.get("data")
                if not isinstance(data, list) or len(data) != len(texts):
                    raise ServiceRequestError("embeddings", "embedding response count did not match the request", 502)
                ordered = sorted(
                    (item for item in data if isinstance(item, dict)),
                    key=lambda item: int(item.get("index", 0)),
                )
                if len(ordered) != len(texts):
                    raise ServiceRequestError("embeddings", "embedding response contained invalid items", 502)
                return [_coerce_vector(item.get("embedding")) for item in ordered]
            except ServiceRequestError as exc:
                last_error = exc
                if not is_transient_service_error(exc) or attempt >= 2:
                    break
                self._backoff(attempt)
        raise OllamaEmbeddingUnavailable((last_error.message if last_error else "embedding request failed")[:500])

    def _backoff(self, attempt: int) -> None:
        delay = self.retry_base_seconds * (2**attempt)
        if delay:
            self._sleep(delay)


def _message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = strip_thinking_content(message["content"])
            if content:
                return content
    raise ServiceRequestError("vllm", "chat response did not include content", 502)


def _coerce_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ServiceRequestError("embeddings", "embedding response did not include a vector", 502)
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ServiceRequestError("embeddings", "embedding vector contained non-numeric values", 502) from exc
    if not all(math.isfinite(item) for item in vector):
        raise ServiceRequestError("embeddings", "embedding vector contained non-finite values", 502)
    return vector


def _openai_path(base_url: str, path: str) -> str:
    return path.removeprefix("/v1") if base_url.rstrip("/").endswith("/v1") else path
