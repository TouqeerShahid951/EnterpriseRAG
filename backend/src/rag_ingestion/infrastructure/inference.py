"""Provider-neutral ingestion inference contract and factory."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol


class IngestionInferenceClient(Protocol):
    def generate_metadata(self, text: str) -> dict[str, Any]: ...

    def embed(self, text: str) -> list[float]: ...

    def embed_many(
        self,
        texts: Sequence[str],
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]: ...


def build_ingestion_inference_client(
    runtime_config: Any,
    *,
    timeout_seconds: float,
    retry_base_seconds: float,
    embedding_batch_size: int,
    num_ctx: int | None = None,
) -> IngestionInferenceClient:
    if runtime_config.provider == "vllm":
        from .openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(
            base_url=runtime_config.ingestion_base_url or runtime_config.base_url,
            embedding_base_url=runtime_config.embedding_base_url,
            chat_model=runtime_config.ingestion_model or runtime_config.chat_model,
            embed_model=runtime_config.embed_model,
            timeout_seconds=timeout_seconds,
            chat_timeout_seconds=runtime_config.chat_timeout_seconds,
            embed_timeout_seconds=runtime_config.embed_timeout_seconds,
            retry_base_seconds=retry_base_seconds,
            embedding_batch_size=embedding_batch_size,
        )

    from .ollama import OllamaClient

    return OllamaClient(
        base_url=runtime_config.base_url,
        chat_model=runtime_config.ingestion_model or runtime_config.chat_model,
        embed_model=runtime_config.embed_model,
        timeout_seconds=timeout_seconds,
        chat_timeout_seconds=runtime_config.chat_timeout_seconds,
        embed_timeout_seconds=runtime_config.embed_timeout_seconds,
        thinking_enabled=runtime_config.thinking_enabled,
        retry_base_seconds=retry_base_seconds,
        embedding_batch_size=embedding_batch_size,
        num_ctx=num_ctx,
    )
