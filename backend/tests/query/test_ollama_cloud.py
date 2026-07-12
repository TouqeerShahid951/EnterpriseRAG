from __future__ import annotations

import pytest

from rag.query import ollama as ollama_module
from rag.query.ollama import OllamaClient


JSON_METHODS = (
    "judge_faithfulness",
    "verify_route",
    "plan_query",
    "rewrite_query",
    "extract_temporal_scope",
    "generate_json",
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


def _capture_json_payload(
    monkeypatch,
    *,
    method_name: str,
    chat_model: str,
    model: str | None = None,
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
    if method_name == "generate_json":
        kwargs["system"] = "You produce strict JSON."

    getattr(client, method_name)(**kwargs)

    assert len(captured) == 1
    return captured[0]
