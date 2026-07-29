"""OpenAI-compatible adapter for vLLM chat and embedding services."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from rag.shared.thinking import (
    no_thinking_payload_fields,
    no_thinking_prompt,
    no_thinking_system,
    strip_thinking_chunks,
    strip_thinking_content,
)

from .cancellation import QueryCancellationToken
from .http import ServiceRequestError, request_json, stream_sse_json
from .ollama import (
    ANSWER_SYSTEM_MESSAGE,
    FAITHFULNESS_NUM_PREDICT,
    REASONING_NUM_PREDICT,
    ROUTE_PLANNER_NUM_PREDICT,
    answer_num_predict_for_profile,
    build_answer_prompt,
)


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        embedding_base_url: str,
        reasoning_base_url: str | None = None,
        routing_base_url: str | None = None,
        faithfulness_base_url: str | None = None,
        ingestion_base_url: str | None = None,
        chat_model: str,
        embed_model: str,
        timeout_seconds: float,
        chat_timeout_seconds: float | None = None,
        embed_timeout_seconds: float | None = None,
        json_num_predict: int = 4096,
    ) -> None:
        self.base_url = base_url
        self.embedding_base_url = embedding_base_url
        self.reasoning_base_url = reasoning_base_url or base_url
        self.routing_base_url = routing_base_url or self.reasoning_base_url
        self.faithfulness_base_url = faithfulness_base_url or base_url
        self.ingestion_base_url = ingestion_base_url or base_url
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.timeout_seconds = timeout_seconds
        self.chat_timeout_seconds = chat_timeout_seconds or timeout_seconds
        self.embed_timeout_seconds = embed_timeout_seconds or timeout_seconds
        self.json_num_predict = json_num_predict

    def embed(self, text: str, *, cancellation_token: QueryCancellationToken | None = None) -> list[float]:
        payload = request_json(
            self.embedding_base_url,
            _openai_path(self.embedding_base_url, "/v1/embeddings"),
            service="embeddings",
            method="POST",
            payload={"model": self.embed_model, "input": [text]},
            timeout_seconds=self.embed_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return _coerce_vector(data[0].get("embedding"))
        raise ServiceRequestError("embeddings", "embedding response did not include a vector", 502)

    def answer(
        self,
        *,
        question: str,
        contexts: list[str],
        profile: str | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self._chat(
            prompt=build_answer_prompt(question=question, contexts=contexts, profile=profile),
            model=self.chat_model,
            system=ANSWER_SYSTEM_MESSAGE,
            max_tokens=answer_num_predict_for_profile(profile),
            temperature=0.1,
            json_response=False,
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
        max_tokens = answer_num_predict_for_profile(profile)
        chunks = stream_sse_json(
            self.base_url,
            _openai_path(self.base_url, "/v1/chat/completions"),
            service="vllm",
            method="POST",
            payload=_chat_payload(
                model=self.chat_model,
                prompt=build_answer_prompt(question=question, contexts=contexts, profile=profile),
                system=ANSWER_SYSTEM_MESSAGE,
                max_tokens=max_tokens,
                temperature=0.1,
                stream=True,
                json_response=False,
            ),
            timeout_seconds=self.chat_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        saw_content = False
        visible_chunks = (
            _delta_content(payload, token_limit=max_tokens)
            for payload in chunks
        )
        for content in strip_thinking_chunks(visible_chunks):
            if content:
                saw_content = True
                yield content
        if not saw_content:
            raise ServiceRequestError("vllm", "chat stream did not include message content", 502)

    def judge_faithfulness(
        self,
        *,
        prompt: str,
        model: str | None,
        json_schema: dict[str, object] | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self._chat(
            prompt=prompt,
            model=model or self.chat_model,
            base_url=self.faithfulness_base_url,
            system="You are a strict RAG faithfulness judge.",
            max_tokens=min(self.json_num_predict, FAITHFULNESS_NUM_PREDICT),
            temperature=0,
            json_response=True,
            json_schema=json_schema,
            cancellation_token=cancellation_token,
        )

    def verify_route(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self._chat(
            prompt=prompt,
            model=model or self.chat_model,
            base_url=self.routing_base_url,
            system="You are a strict typed RAG capability planner.",
            max_tokens=ROUTE_PLANNER_NUM_PREDICT,
            temperature=0,
            json_response=True,
            cancellation_token=cancellation_token,
        )

    def plan_query(self, *, prompt: str, model: str | None, cancellation_token=None) -> str:
        return self._reasoning_chat(
            prompt, model, self.reasoning_base_url, "You are a strict enterprise RAG query planner.", cancellation_token
        )

    def rewrite_query(self, *, prompt: str, model: str | None, cancellation_token=None) -> str:
        return self._reasoning_chat(
            prompt, model, self.reasoning_base_url, "You rewrite failed enterprise RAG retrieval queries.", cancellation_token
        )

    def extract_temporal_scope(self, *, prompt: str, model: str | None, cancellation_token=None) -> str:
        return self._reasoning_chat(
            prompt, model, self.reasoning_base_url, "You extract dates and temporal scope for enterprise RAG retrieval.", cancellation_token
        )

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        json_schema: dict[str, object] | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self._chat(
            prompt=prompt,
            model=model or self.chat_model,
            base_url=self.reasoning_base_url,
            system=system,
            max_tokens=max_tokens or self.json_num_predict,
            temperature=0,
            json_response=True,
            json_schema=json_schema,
            cancellation_token=cancellation_token,
            timeout_seconds=timeout_seconds,
        )

    def generate_routing_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self.generate_json(
            prompt=prompt,
            model=model,
            system=system,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            cancellation_token=cancellation_token,
        )

    def _reasoning_chat(
        self,
        prompt: str,
        model: str | None,
        base_url: str,
        system: str,
        cancellation_token: QueryCancellationToken | None,
    ) -> str:
        return self._chat(
            prompt=prompt,
            model=model or self.chat_model,
            base_url=base_url,
            system=system,
            max_tokens=REASONING_NUM_PREDICT,
            temperature=0,
            json_response=True,
            cancellation_token=cancellation_token,
        )

    def _chat(
        self,
        *,
        prompt: str,
        model: str,
        base_url: str | None = None,
        system: str,
        max_tokens: int,
        temperature: float,
        json_response: bool,
        json_schema: dict[str, object] | None = None,
        cancellation_token: QueryCancellationToken | None,
        timeout_seconds: float | None = None,
    ) -> str:
        selected_base_url = base_url or self.base_url
        payload = request_json(
            selected_base_url,
            _openai_path(selected_base_url, "/v1/chat/completions"),
            service="vllm",
            method="POST",
            payload=_chat_payload(
                model=model,
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
                json_response=json_response,
                json_schema=json_schema,
            ),
            timeout_seconds=timeout_seconds or self.chat_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        _raise_if_answer_truncated(payload, token_limit=max_tokens)
        return _message_content(payload)


def _chat_payload(
    *,
    model: str,
    prompt: str,
    system: str,
    max_tokens: int,
    temperature: float,
    stream: bool,
    json_response: bool,
    json_schema: dict[str, object] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": no_thinking_system(system)},
            {"role": "user", "content": no_thinking_prompt(prompt, model)},
        ],
        **no_thinking_payload_fields(),
    }
    if json_response:
        payload["response_format"] = (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "rag_structured_output",
                    "strict": True,
                    "schema": json_schema,
                },
            }
            if json_schema is not None
            else {"type": "json_object"}
        )
    return payload


def _message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = strip_thinking_content(message["content"])
            if content:
                return content
    raise ServiceRequestError("vllm", "chat response did not include message content", 502)


def _raise_if_answer_truncated(
    payload: dict[str, Any],
    *,
    token_limit: int,
) -> None:
    choices = payload.get("choices")
    finish_reason = (
        choices[0].get("finish_reason")
        if isinstance(choices, list)
        and choices
        and isinstance(choices[0], dict)
        else None
    )
    usage = payload.get("usage")
    completion_tokens = (
        usage.get("completion_tokens")
        if isinstance(usage, dict)
        else None
    )
    reached_limit = (
        isinstance(completion_tokens, int)
        and not isinstance(completion_tokens, bool)
        and completion_tokens >= token_limit
    )
    if finish_reason == "length" or reached_limit:
        raise ServiceRequestError(
            "vllm",
            "chat generation reached its output token limit",
            502,
        )


def _delta_content(payload: dict[str, Any], *, token_limit: int) -> str:
    _raise_if_answer_truncated(payload, token_limit=token_limit)
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        delta = choices[0].get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            return delta["content"]
    return ""


def _coerce_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ServiceRequestError("embeddings", "embedding response did not include a vector", 502)
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ServiceRequestError("embeddings", "embedding vector contained non-numeric values", 502) from exc


def _openai_path(base_url: str, path: str) -> str:
    return path.removeprefix("/v1") if base_url.rstrip("/").endswith("/v1") else path
