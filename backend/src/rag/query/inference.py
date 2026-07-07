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
        profile: str | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...

    def stream_answer(
        self,
        *,
        question: str,
        contexts: list[str],
        profile: str | None = None,
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
        max_tokens: int | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str: ...


def build_inference_client(config: RagConfigRecord, *, settings: Settings) -> InferenceClient:
    return RoleRoutedInferenceClient(
        chat_client=_build_language_client_for_role(config, "chat", settings=settings),
        reasoning_client=_build_language_client_for_role(config, "reasoning", settings=settings),
        routing_client=_build_language_client_for_role(config, "routing", settings=settings),
        faithfulness_client=_build_language_client_for_role(config, "faithfulness", settings=settings),
        ingestion_client=_build_language_client_for_role(config, "ingestion", settings=settings),
        embedding_client=_build_embedding_client(config, settings=settings),
    )


class RoleRoutedInferenceClient:
    def __init__(
        self,
        *,
        chat_client: InferenceClient,
        reasoning_client: InferenceClient,
        routing_client: InferenceClient,
        faithfulness_client: InferenceClient,
        ingestion_client: InferenceClient,
        embedding_client: object,
    ) -> None:
        self.chat_client = chat_client
        self.reasoning_client = reasoning_client
        self.routing_client = routing_client
        self.faithfulness_client = faithfulness_client
        self.ingestion_client = ingestion_client
        self.embedding_client = embedding_client
        self.chat_model = getattr(chat_client, "chat_model", "")
        self.embed_model = getattr(embedding_client, "embed_model", "")

    def embed(self, text: str, *, cancellation_token: QueryCancellationToken | None = None) -> list[float]:
        return self.embedding_client.embed(text, cancellation_token=cancellation_token)  # type: ignore[attr-defined]

    def answer(
        self,
        *,
        question: str,
        contexts: list[str],
        profile: str | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.chat_client.answer(
            question=question,
            contexts=contexts,
            profile=profile,
            cancellation_token=cancellation_token,
        )

    def stream_answer(
        self,
        *,
        question: str,
        contexts: list[str],
        profile: str | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> Iterator[str]:
        return self.chat_client.stream_answer(
            question=question,
            contexts=contexts,
            profile=profile,
            cancellation_token=cancellation_token,
        )

    def judge_faithfulness(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.faithfulness_client.judge_faithfulness(
            prompt=prompt,
            model=model,
            cancellation_token=cancellation_token,
        )

    def verify_route(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.routing_client.verify_route(prompt=prompt, model=model, cancellation_token=cancellation_token)

    def plan_query(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.reasoning_client.plan_query(prompt=prompt, model=model, cancellation_token=cancellation_token)

    def rewrite_query(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.reasoning_client.rewrite_query(prompt=prompt, model=model, cancellation_token=cancellation_token)

    def extract_temporal_scope(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.reasoning_client.extract_temporal_scope(
            prompt=prompt,
            model=model,
            cancellation_token=cancellation_token,
        )

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        max_tokens: int | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.reasoning_client.generate_json(
            prompt=prompt,
            model=model,
            system=system,
            max_tokens=max_tokens,
            cancellation_token=cancellation_token,
        )


class SplitEmbeddingInferenceClient:
    def __init__(self, *, language_client: InferenceClient, embedding_client: object) -> None:
        self.language_client = language_client
        self.embedding_client = embedding_client
        self.chat_model = getattr(language_client, "chat_model", "")
        self.embed_model = getattr(embedding_client, "embed_model", getattr(language_client, "embed_model", ""))

    def embed(self, text: str, *, cancellation_token: QueryCancellationToken | None = None) -> list[float]:
        return self.embedding_client.embed(text, cancellation_token=cancellation_token)  # type: ignore[attr-defined]

    def answer(
        self,
        *,
        question: str,
        contexts: list[str],
        profile: str | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.language_client.answer(
            question=question,
            contexts=contexts,
            profile=profile,
            cancellation_token=cancellation_token,
        )

    def stream_answer(
        self,
        *,
        question: str,
        contexts: list[str],
        profile: str | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> Iterator[str]:
        return self.language_client.stream_answer(
            question=question,
            contexts=contexts,
            profile=profile,
            cancellation_token=cancellation_token,
        )

    def judge_faithfulness(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.language_client.judge_faithfulness(prompt=prompt, model=model, cancellation_token=cancellation_token)

    def verify_route(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.language_client.verify_route(prompt=prompt, model=model, cancellation_token=cancellation_token)

    def plan_query(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.language_client.plan_query(prompt=prompt, model=model, cancellation_token=cancellation_token)

    def rewrite_query(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.language_client.rewrite_query(prompt=prompt, model=model, cancellation_token=cancellation_token)

    def extract_temporal_scope(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.language_client.extract_temporal_scope(prompt=prompt, model=model, cancellation_token=cancellation_token)

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        max_tokens: int | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.language_client.generate_json(
            prompt=prompt,
            model=model,
            system=system,
            max_tokens=max_tokens,
            cancellation_token=cancellation_token,
        )


def _build_embedding_client(config: RagConfigRecord, *, settings: Settings) -> object:
    if config.embedding_provider == "fastembed":
        from .fastembed_dense import FastEmbedDenseEmbeddingClient

        return FastEmbedDenseEmbeddingClient(
            model_name=config.embed_model,
            cache_dir=settings.rag_dense_cache_dir,
        )
    provider = "vllm" if config.embedding_provider == "openai_compatible" else "ollama"
    return _build_provider_client(
        provider=provider,
        base_url=config.embedding_base_url,
        chat_model=config.chat_model,
        embed_model=config.embed_model,
        config=config,
        settings=settings,
    )


def _build_language_client_for_role(config: RagConfigRecord, role: str, *, settings: Settings) -> InferenceClient:
    provider = config.provider if role == "chat" else config.role_provider(role)
    base_url = config.base_url if role == "chat" else config._role_base_url(role)
    model = _role_model(config, role)
    return _build_provider_client(
        provider=provider,
        base_url=base_url,
        chat_model=model,
        embed_model=config.embed_model,
        config=config,
        settings=settings,
    )


def _build_provider_client(
    *,
    provider: str,
    base_url: str,
    chat_model: str,
    embed_model: str,
    config: RagConfigRecord,
    settings: Settings,
) -> InferenceClient:
    if provider == "vllm":
        from .openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(
            base_url=base_url,
            embedding_base_url=base_url,
            reasoning_base_url=base_url,
            routing_base_url=base_url,
            faithfulness_base_url=base_url,
            ingestion_base_url=base_url,
            chat_model=chat_model,
            embed_model=embed_model,
            timeout_seconds=settings.rag_http_timeout_seconds,
            chat_timeout_seconds=config.chat_timeout_seconds,
            embed_timeout_seconds=config.embed_timeout_seconds,
            json_num_predict=config.json_num_predict,
        )

    from .ollama import OllamaClient

    return OllamaClient(
        base_url=base_url,
        chat_model=chat_model,
        embed_model=embed_model,
        timeout_seconds=settings.rag_http_timeout_seconds,
        chat_timeout_seconds=config.chat_timeout_seconds,
        embed_timeout_seconds=config.embed_timeout_seconds,
        thinking_enabled=config.thinking_enabled,
        json_num_predict=config.json_num_predict,
        num_ctx=settings.ollama_num_ctx,
    )


def _role_model(config: RagConfigRecord, role: str) -> str:
    if role == "chat":
        return config.chat_model
    if role == "reasoning":
        return config.effective_reasoning_model or config.chat_model
    if role == "routing":
        return config.routing_model or config.effective_reasoning_model or config.chat_model
    if role == "faithfulness":
        return config.faithfulness_model or config.chat_model
    if role == "ingestion":
        return config.ingestion_model or config.chat_model
    return config.chat_model
