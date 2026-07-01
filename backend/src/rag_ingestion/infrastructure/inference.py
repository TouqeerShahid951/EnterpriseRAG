"""Provider-neutral ingestion inference contract and factory."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol


class IngestionInferenceClient(Protocol):
    def generate_metadata(self, text: str) -> dict[str, Any]: ...

    def generate_json(self, *, prompt: str, model: str | None = None, system: str) -> str: ...

    def embed(self, text: str) -> list[float]: ...

    def embed_many(
        self,
        texts: Sequence[str],
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]: ...


class SplitEmbeddingInferenceClient:
    def __init__(self, *, language_client: IngestionInferenceClient, embedding_client: object) -> None:
        self.language_client = language_client
        self.embedding_client = embedding_client
        self.chat_model = getattr(language_client, "chat_model", "")
        self.embed_model = getattr(embedding_client, "embed_model", getattr(language_client, "embed_model", ""))

    def generate_metadata(self, text: str) -> dict[str, Any]:
        return self.language_client.generate_metadata(text)

    def generate_json(self, *, prompt: str, model: str | None = None, system: str) -> str:
        return self.language_client.generate_json(prompt=prompt, model=model, system=system)

    def embed(self, text: str) -> list[float]:
        return self.embedding_client.embed(text)  # type: ignore[attr-defined]

    def embed_many(
        self,
        texts: Sequence[str],
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        return self.embedding_client.embed_many(texts, progress=progress)  # type: ignore[attr-defined]


def build_ingestion_inference_client(
    runtime_config: Any,
    *,
    timeout_seconds: float,
    retry_base_seconds: float,
    embedding_batch_size: int,
    dense_cache_dir: str | None = None,
    num_ctx: int | None = None,
) -> IngestionInferenceClient:
    language_client = _build_language_inference_client(
        runtime_config,
        timeout_seconds=timeout_seconds,
        retry_base_seconds=retry_base_seconds,
        embedding_batch_size=embedding_batch_size,
        num_ctx=num_ctx,
    )
    if getattr(runtime_config, "embedding_provider", "") == "fastembed":
        from .fastembed_dense import FastEmbedDenseClient

        return SplitEmbeddingInferenceClient(
            language_client=language_client,
            embedding_client=FastEmbedDenseClient(
                model_name=runtime_config.embed_model,
                cache_dir=dense_cache_dir,
                batch_size=embedding_batch_size,
            ),
        )
    return SplitEmbeddingInferenceClient(
        language_client=language_client,
        embedding_client=_build_embedding_inference_client(
            runtime_config,
            timeout_seconds=timeout_seconds,
            retry_base_seconds=retry_base_seconds,
            embedding_batch_size=embedding_batch_size,
            num_ctx=num_ctx,
        ),
    )


def _build_language_inference_client(
    runtime_config: Any,
    *,
    timeout_seconds: float,
    retry_base_seconds: float,
    embedding_batch_size: int,
    num_ctx: int | None,
) -> IngestionInferenceClient:
    provider = getattr(runtime_config, "ingestion_provider", None) or runtime_config.provider
    if provider == "vllm":
        from .openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(
            base_url=runtime_config.ingestion_base_url or runtime_config.base_url,
            embedding_base_url=runtime_config.ingestion_base_url or runtime_config.base_url,
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
        base_url=runtime_config.ingestion_base_url or runtime_config.base_url,
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


def _build_embedding_inference_client(
    runtime_config: Any,
    *,
    timeout_seconds: float,
    retry_base_seconds: float,
    embedding_batch_size: int,
    num_ctx: int | None,
) -> IngestionInferenceClient:
    embedding_provider = getattr(runtime_config, "embedding_provider", "")
    if embedding_provider == "openai_compatible":
        from .openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(
            base_url=runtime_config.embedding_base_url,
            embedding_base_url=runtime_config.embedding_base_url,
            chat_model=runtime_config.chat_model,
            embed_model=runtime_config.embed_model,
            timeout_seconds=timeout_seconds,
            chat_timeout_seconds=runtime_config.chat_timeout_seconds,
            embed_timeout_seconds=runtime_config.embed_timeout_seconds,
            retry_base_seconds=retry_base_seconds,
            embedding_batch_size=embedding_batch_size,
        )

    from .ollama import OllamaClient

    return OllamaClient(
        base_url=runtime_config.embedding_base_url or runtime_config.base_url,
        chat_model=runtime_config.chat_model,
        embed_model=runtime_config.embed_model,
        timeout_seconds=timeout_seconds,
        chat_timeout_seconds=runtime_config.chat_timeout_seconds,
        embed_timeout_seconds=runtime_config.embed_timeout_seconds,
        thinking_enabled=runtime_config.thinking_enabled,
        retry_base_seconds=retry_base_seconds,
        embedding_batch_size=embedding_batch_size,
        num_ctx=num_ctx,
    )
