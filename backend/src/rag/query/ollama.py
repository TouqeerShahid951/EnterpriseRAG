"""Ollama adapter for the local RAG pilot."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .cancellation import QueryCancellationToken
from .http import ServiceRequestError, request_json, stream_json_lines


ANSWER_NUM_PREDICT = 2048
FAITHFULNESS_NUM_PREDICT = 1024
ROUTE_VERIFIER_NUM_PREDICT = 512
REASONING_NUM_PREDICT = 512
JSON_NUM_PREDICT = 4096


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
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        prompt = build_answer_prompt(question=question, contexts=contexts)
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
        cancellation_token: QueryCancellationToken | None = None,
    ) -> Iterator[str]:
        prompt = build_answer_prompt(question=question, contexts=contexts)
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
        cancellation_token: QueryCancellationToken | None = None,
    ) -> str:
        return self._reasoning_chat(
            prompt=prompt,
            model=model,
            system=system,
            empty_message="JSON generation response did not include message content",
            num_predict=self.json_num_predict,
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


def build_answer_prompt(*, question: str, contexts: list[str]) -> str:
    context_block = "\n\n".join(contexts)
    return (
        "Answer the question directly using only the provided evidence. "
        "Each evidence block starts with its required citation label in square brackets. "
        "Cite every factual claim with the exact label of a source that directly supports that claim. "
        "Do not invent citation labels or cite an unrelated source. "
        "Do not refer to evidence blocks as Source 1, Source 2, or similar ordinal names. "
        "Ignore evidence that is unrelated to the question. "
        "For list questions, include every supported item found in directly relevant evidence. "
        "If a table row directly answers the question and uses Row/Value fields, preserve the full Value content unless the question asks for a narrower subset. "
        "For option, list, or supported-item questions, answer from the directly matching row or section and do not add related rows, comparison rows, or examples after the direct answer is complete. "
        "If the question asks for named fields, include each requested field when it appears in evidence; if a requested field is not present, say it is not present in the evidence. "
        "For highest, lowest, maximum, or minimum questions over table evidence, include the deciding table value as well as the requested fields, but do not verify a superlative from only one candidate row. "
        "When a table header or cell uses slash-paired labels such as X/Y, preserve the paired cell exactly and do not reinterpret the second value as the first label. "
        "When relevant evidence is a table, treat each named row as a candidate answer and do not stop after examples. "
        "Include software, embedded, or system-board entries unless the question explicitly excludes them. "
        "If the sources do not contain the answer, say that the indexed sources do not contain enough information.\n\n"
        f"Evidence:\n{context_block}\n\nQuestion: {question}"
    )


def _answer_payload(
    *,
    model: str,
    prompt: str,
    stream: bool,
    thinking_enabled: bool,
    num_ctx: int | None,
) -> dict[str, Any]:
    return {
        "model": model,
        "stream": stream,
        "think": thinking_enabled,
        "options": _ollama_options(temperature=0.1, num_predict=ANSWER_NUM_PREDICT, num_ctx=num_ctx),
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
