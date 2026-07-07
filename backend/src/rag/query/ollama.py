"""Ollama adapter for the local RAG pilot."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .cancellation import QueryCancellationToken
from .http import ServiceRequestError, request_json, stream_json_lines


ANSWER_NUM_PREDICT = 1024
LONG_ANSWER_NUM_PREDICT = 2048
SYNTHESIS_PROMPT_HEADROOM_TOKENS = 512
FAITHFULNESS_NUM_PREDICT = 1024
ROUTE_VERIFIER_NUM_PREDICT = 512
REASONING_NUM_PREDICT = 512
JSON_NUM_PREDICT = 4096
_LONG_ANSWER_PROFILES = {
    "aggregation",
    "comparison",
    "comparative_summary",
    "conflict_check",
    "document_navigation",
    "graphrag_global",
    "legacy",
    "multi_hop",
    "summarization",
    "temporal_comparison",
}
_BASE_ANSWER_PREFIX = (
    "Use only evidence. Cite factual claims with the exact bracket label from the supporting block.",
    "Ignore unrelated evidence. Do not invent labels or use ordinal source names.",
)
_BASE_ANSWER_SUFFIX = (
    "If evidence lacks the answer, say the indexed sources do not contain enough information.",
)
_LIST_ANSWER_INSTRUCTIONS = (
    "For lists, include all directly supported matching items and stop after the direct answer.",
)
_TABLE_ANSWER_INSTRUCTIONS = (
    "For table Row/Value evidence, preserve full Value unless asked narrower; include requested fields or say absent.",
    "For highest/lowest/max/min, cite the deciding value; do not verify a superlative from one candidate row.",
    "Preserve slash-paired X/Y cells exactly.",
    "Treat named table rows as candidate answers; include software, embedded, or system-board entries unless excluded.",
)
_LEGACY_ANSWER_INSTRUCTIONS = (
    *_BASE_ANSWER_PREFIX,
    *_LIST_ANSWER_INSTRUCTIONS,
    *_TABLE_ANSWER_INSTRUCTIONS,
    *_BASE_ANSWER_SUFFIX,
)
_LIST_ANSWER_PROFILES = {
    "aggregation",
    "comparison",
    "comparative_summary",
    "document_navigation",
    "multi_hop",
    "summarization",
    "temporal_comparison",
}
_TABLE_ANSWER_PROFILES = {
    "aggregation",
    "comparison",
    "comparative_summary",
    "document_navigation",
    "temporal_comparison",
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
        json_num_predict: int = JSON_NUM_PREDICT,
        num_ctx: int | None = None,
    ) -> None:
        self.base_url = base_url
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.timeout_seconds = timeout_seconds
        self.chat_timeout_seconds = chat_timeout_seconds or timeout_seconds
        self.embed_timeout_seconds = embed_timeout_seconds or timeout_seconds
        self.thinking_enabled = thinking_enabled
        self.json_num_predict = json_num_predict
        self.num_ctx = num_ctx

    def embed(self, text: str, *, cancellation_token: QueryCancellationToken | None = None) -> list[float]:
        try:
            payload = request_json(
                self.base_url,
                "/api/embed",
                service="ollama",
                method="POST",
                payload={"model": self.embed_model, "input": text},
                timeout_seconds=self.embed_timeout_seconds,
                cancellation_token=cancellation_token,
            )
            embeddings = payload.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                return _coerce_vector(embeddings[0])
        except ServiceRequestError as exc:
            if exc.status_code not in (404, 400):
                raise

        payload = request_json(
            self.base_url,
            "/api/embeddings",
            service="ollama",
            method="POST",
            payload={"model": self.embed_model, "prompt": text},
            timeout_seconds=self.embed_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _coerce_vector(payload.get("embedding"))

    def answer(
        self,
        *,
        question: str,
        contexts: list[str],
        profile: str | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        prompt = build_answer_prompt(question=question, contexts=contexts, profile=profile)
        payload = request_json(
            self.base_url,
            "/api/chat",
            service="ollama",
            method="POST",
            payload=_answer_payload(
                model=self.chat_model,
                prompt=prompt,
                stream=False,
                thinking_enabled=self.thinking_enabled,
                num_ctx=self.num_ctx,
                num_predict=answer_num_predict_for_profile(profile),
            ),
            timeout_seconds=self.chat_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _message_content(payload, "chat response did not include message content")

    def stream_answer(
        self,
        *,
        question: str,
        contexts: list[str],
        profile: str | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> Iterator[str]:
        prompt = build_answer_prompt(question=question, contexts=contexts, profile=profile)
        chunks = stream_json_lines(
            self.base_url,
            "/api/chat",
            service="ollama",
            method="POST",
            payload=_answer_payload(
                model=self.chat_model,
                prompt=prompt,
                stream=True,
                thinking_enabled=self.thinking_enabled,
                num_ctx=self.num_ctx,
                num_predict=answer_num_predict_for_profile(profile),
            ),
            timeout_seconds=self.chat_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        yield from _message_content_chunks(chunks, "chat stream did not include message content")

    def judge_faithfulness(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        payload = request_json(
            self.base_url,
            "/api/chat",
            service="ollama",
            method="POST",
            payload={
                "model": model or self.chat_model,
                "stream": False,
                "format": "json",
                "think": self.thinking_enabled,
                "options": _ollama_options(
                    temperature=0.0,
                    num_predict=min(self.json_num_predict, FAITHFULNESS_NUM_PREDICT),
                    num_ctx=self.num_ctx,
                ),
                "messages": [
                    {"role": "system", "content": "You are a strict RAG faithfulness judge."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout_seconds=self.chat_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _message_content(payload, "faithfulness response did not include message content")

    def verify_route(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        payload = request_json(
            self.base_url,
            "/api/chat",
            service="ollama",
            method="POST",
            payload={
                "model": model or self.chat_model,
                "stream": False,
                "format": "json",
                "think": self.thinking_enabled,
                "options": _ollama_options(
                    temperature=0.0,
                    num_predict=ROUTE_VERIFIER_NUM_PREDICT,
                    num_ctx=self.num_ctx,
                ),
                "messages": [
                    {"role": "system", "content": "You are a strict RAG intent routing verifier."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout_seconds=self.chat_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _message_content(payload, "route verifier response did not include message content")

    def plan_query(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self._reasoning_chat(
            prompt=prompt,
            model=model,
            system="You are a strict enterprise RAG query planner.",
            empty_message="query planner response did not include message content",
            cancellation_token=cancellation_token,
        )

    def rewrite_query(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self._reasoning_chat(
            prompt=prompt,
            model=model,
            system="You rewrite failed enterprise RAG retrieval queries.",
            empty_message="query rewrite response did not include message content",
            cancellation_token=cancellation_token,
        )

    def extract_temporal_scope(
        self,
        *,
        prompt: str,
        model: str | None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self._reasoning_chat(
            prompt=prompt,
            model=model,
            system="You extract dates and temporal scope for enterprise RAG retrieval.",
            empty_message="temporal scope response did not include message content",
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
        return self._reasoning_chat(
            prompt=prompt,
            model=model,
            system=system,
            empty_message="JSON generation response did not include message content",
            num_predict=max_tokens or self.json_num_predict,
            cancellation_token=cancellation_token,
        )

    def _reasoning_chat(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        empty_message: str,
        cancellation_token: QueryCancellationToken | None,
        num_predict: int = REASONING_NUM_PREDICT,
    ) -> str:
        payload = request_json(
            self.base_url,
            "/api/chat",
            service="ollama",
            method="POST",
            payload={
                "model": model or self.chat_model,
                "stream": False,
                "format": "json",
                "think": self.thinking_enabled,
                "options": _ollama_options(temperature=0.0, num_predict=num_predict, num_ctx=self.num_ctx),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout_seconds=self.chat_timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _message_content(payload, empty_message)


def build_answer_prompt(*, question: str, contexts: list[str], profile: str | None = None) -> str:
    context_block = "\n\n".join(contexts)
    instructions = " ".join(_answer_instructions(profile=profile, contexts=contexts))
    return f"{instructions}\n\nEvidence:\n{context_block}\n\nQuestion: {question}"


def estimate_answer_prompt_tokens(*, question: str, contexts: list[str], profile: str | None = None) -> int:
    return max(1, len(build_answer_prompt(question=question, contexts=contexts, profile=profile)) // 4)


def answer_num_predict_for_profile(profile: str | None) -> int:
    normalized_profile = (profile or "legacy").strip().lower()
    return LONG_ANSWER_NUM_PREDICT if normalized_profile in _LONG_ANSWER_PROFILES else ANSWER_NUM_PREDICT


def _answer_instructions(*, profile: str | None, contexts: list[str]) -> tuple[str, ...]:
    normalized_profile = (profile or "legacy").strip().lower()
    if normalized_profile == "legacy":
        return _LEGACY_ANSWER_INSTRUCTIONS
    instructions = [*_BASE_ANSWER_PREFIX]
    if normalized_profile in _LIST_ANSWER_PROFILES:
        instructions.extend(_LIST_ANSWER_INSTRUCTIONS)
    if normalized_profile in _TABLE_ANSWER_PROFILES or _has_table_context(contexts):
        instructions.extend(_TABLE_ANSWER_INSTRUCTIONS)
    instructions.extend(_BASE_ANSWER_SUFFIX)
    return tuple(instructions)


def _has_table_context(contexts: list[str]) -> bool:
    return any("[Columns:" in context and "Value:" in context for context in contexts)


def _answer_payload(
    *,
    model: str,
    prompt: str,
    stream: bool,
    thinking_enabled: bool,
    num_ctx: int | None,
    num_predict: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "stream": stream,
        "think": thinking_enabled,
        "options": _ollama_options(temperature=0.1, num_predict=num_predict, num_ctx=num_ctx),
        "messages": [
            {"role": "system", "content": "You are a concise enterprise RAG assistant."},
            {"role": "user", "content": prompt},
        ],
    }


def _ollama_options(*, temperature: float, num_predict: int, num_ctx: int | None) -> dict[str, int | float]:
    options: dict[str, int | float] = {"temperature": temperature, "num_predict": num_predict}
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    return options


def _coerce_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ServiceRequestError("ollama", "embedding response did not include a vector")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ServiceRequestError("ollama", "embedding vector contained non-numeric values", 502) from exc


def _message_content(payload: dict[str, Any], empty_message: str) -> str:
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        content = message["content"].strip()
        if content:
            return content
    if isinstance(payload.get("response"), str):
        content = payload["response"].strip()
        if content:
            return content
    raise ServiceRequestError("ollama", empty_message)


def _message_content_chunks(chunks: Iterator[dict[str, Any]], empty_message: str) -> Iterator[str]:
    saw_content = False
    for payload in chunks:
        message = payload.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = message["content"]
            if content:
                if content.strip():
                    saw_content = True
                yield content
            continue
        if isinstance(payload.get("response"), str):
            content = payload["response"]
            if content:
                if content.strip():
                    saw_content = True
                yield content
    if not saw_content:
        raise ServiceRequestError("ollama", empty_message)
