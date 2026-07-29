from __future__ import annotations

import pytest

from rag.query import ollama as ollama_module
from rag.query.http import ServiceRequestError
from rag.query.inference import RoleRoutedInferenceClient
from rag.query.ollama import OllamaClient


JSON_METHODS = (
    "judge_faithfulness",
    "verify_route",
    "plan_query",
    "rewrite_query",
    "extract_temporal_scope",
    "generate_json",
    "generate_routing_json",
)


@pytest.mark.parametrize("method_name", JSON_METHODS)
def test_json_methods_omit_format_for_cloud_models(
    monkeypatch, method_name: str
) -> None:
    payload = _capture_json_payload(
        monkeypatch, method_name=method_name, chat_model="qwen3.5:cloud"
    )

    assert "format" not in payload
    assert (
        payload["messages"][-1]["content"] == "Return only the requested JSON object."
    )


@pytest.mark.parametrize("method_name", JSON_METHODS)
def test_json_methods_keep_json_format_for_local_models(
    monkeypatch, method_name: str
) -> None:
    payload = _capture_json_payload(
        monkeypatch, method_name=method_name, chat_model="qwen3.5:9b"
    )

    assert payload["format"] == "json"


def test_explicit_cloud_role_model_omits_format(monkeypatch) -> None:
    payload = _capture_json_payload(
        monkeypatch,
        method_name="verify_route",
        chat_model="qwen3.5:9b",
        model="qwen3.5:cloud",
    )

    assert payload["model"] == "qwen3.5:cloud"
    assert "format" not in payload


def test_sized_cloud_tag_omits_format(monkeypatch) -> None:
    payload = _capture_json_payload(
        monkeypatch,
        method_name="generate_json",
        chat_model="gemma4:31b-cloud",
    )

    assert "format" not in payload


def test_local_generate_json_uses_exact_schema_on_first_request(monkeypatch) -> None:
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }

    payload = _capture_json_payload(
        monkeypatch,
        method_name="generate_json",
        chat_model="qwen3:8b",
        json_schema=schema,
    )

    assert payload["format"] is schema


def test_cloud_generate_json_rejects_unenforceable_schema(monkeypatch) -> None:
    called = False

    def fake_request_json(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"message": {"content": "{}"}}

    monkeypatch.setattr(ollama_module, "request_json", fake_request_json)
    client = OllamaClient(
        base_url="http://ollama.local",
        chat_model="nemotron-3-super:cloud",
        embed_model="embed-model",
        timeout_seconds=45,
    )

    with pytest.raises(
        ServiceRequestError,
        match="does not support schema-constrained output",
    ):
        client.generate_json(
            prompt="Return status.",
            model=None,
            system="Return valid JSON.",
            json_schema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
        )

    assert called is False


def test_role_router_preserves_schema_for_first_request() -> None:
    role_client = _RecordingRoleClient()
    client = RoleRoutedInferenceClient(
        chat_client=role_client,  # type: ignore[arg-type]
        reasoning_client=role_client,  # type: ignore[arg-type]
        routing_client=role_client,  # type: ignore[arg-type]
        faithfulness_client=role_client,  # type: ignore[arg-type]
        ingestion_client=role_client,  # type: ignore[arg-type]
        embedding_client=role_client,
    )
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }

    client.generate_json(
        prompt="Return status.",
        model=None,
        system="Return valid JSON.",
        json_schema=schema,
    )
    client.judge_faithfulness(
        prompt="Judge.",
        model=None,
        json_schema=schema,
    )

    assert role_client.calls[0]["json_schema"] is schema
    assert role_client.calls[1]["json_schema"] is schema


class _RecordingRoleClient:
    chat_model = "model"
    embed_model = "embed"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_json(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "{}"

    def judge_faithfulness(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "{}"


def _capture_json_payload(
    monkeypatch,
    *,
    method_name: str,
    chat_model: str,
    model: str | None = None,
    json_schema: dict[str, object] | None = None,
) -> dict[str, object]:
    captured: list[dict[str, object]] = []

    def fake_request_json(*_args, **kwargs):
        captured.append(kwargs["payload"])
        return {"message": {"content": "{}"}}

    monkeypatch.setattr(ollama_module, "request_json", fake_request_json)
    client = OllamaClient(
        base_url="http://ollama.local",
        chat_model=chat_model,
        embed_model="embed-model",
        timeout_seconds=45,
    )
    kwargs: dict[str, object] = {
        "prompt": "Return only the requested JSON object.",
        "model": model,
    }
    if method_name in {"generate_json", "generate_routing_json"}:
        kwargs["system"] = "You produce strict JSON."
    if json_schema is not None:
        kwargs["json_schema"] = json_schema

    getattr(client, method_name)(**kwargs)

    assert len(captured) == 1
    return captured[0]
