"""Provider-neutral inference client contract and factory."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from ..core.config import Settings
from ..repositories.rag_config import RagConfigRecord
from .cancellation import QueryCancellationToken


class InferenceClient(Protocol):
    def embed(self, text: str, *, cancellation_token: QueryCancellationToken | None = None) -> list[float]: ...

    def answer(
        self,
        *,
        question: str,
        contexts: list[str],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...

    def stream_answer(
        self,
        *,
        question: str,
        contexts: list[str],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> Iterator[str]: ...

    def judge_faithfulness(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...

    def verify_route(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...

    def plan_query(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...

    def rewrite_query(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...

    def extract_temporal_scope(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...


def build_inference_client(config: RagConfigRecord, *, settings: Settings) -> InferenceClient:
    if config.provider == "vllm":
        from .openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(
            base_url=config.base_url,
            embedding_base_url=config.embedding_base_url,
            reasoning_base_url=config.effective_reasoning_base_url,
            routing_base_url=config.effective_routing_base_url,
            faithfulness_base_url=config.effective_faithfulness_base_url,
            ingestion_base_url=config.effective_ingestion_base_url,
            chat_model=config.chat_model,
            embed_model=config.embed_model,
            timeout_seconds=settings.rag_http_timeout_seconds,
            chat_timeout_seconds=config.chat_timeout_seconds,
            embed_timeout_seconds=config.embed_timeout_seconds,
            json_num_predict=config.json_num_predict,
        )

    from .ollama import OllamaClient

    return OllamaClient(
        base_url=config.base_url,
        chat_model=config.chat_model,
        embed_model=config.embed_model,
        timeout_seconds=settings.rag_http_timeout_seconds,
        chat_timeout_seconds=config.chat_timeout_seconds,
        embed_timeout_seconds=config.embed_timeout_seconds,
        thinking_enabled=config.thinking_enabled,
        json_num_predict=config.json_num_predict,
        num_ctx=settings.ollama_num_ctx,
    )
