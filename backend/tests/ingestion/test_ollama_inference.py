from __future__ import annotations

import json

from rag.ingestion.adapters import ollama as ollama_module
from rag.ingestion.adapters.ollama import OllamaClient
from rag.ingestion.adapters.http import ServiceRequestError


def test_ollama_metadata_request_includes_context_limit(monkeypatch) -> None:
    calls = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {
            "message": {
                "content": json.dumps(
                    {
                        "summary": "A concise factual summary.",
                        "llm_topics": ["contracts"],
                        "doc_type": "policy",
                        "claims": [],
                    }
                )
            }
        }

    monkeypatch.setattr(ollama_module, "request_json", fake_request_json)
    client = OllamaClient(
        base_url="http://ollama:11434",
        chat_model="qwen3.5:27b",
        embed_model="nomic-embed-text:latest",
        timeout_seconds=45,
        num_ctx=16384,
    )

    client.generate_metadata("document text")

    payload = calls[0][2]["payload"]
    assert payload["options"]["num_ctx"] == 16384
    assert payload["options"]["num_predict"] == ollama_module.METADATA_NUM_PREDICT
    assert payload["format"]["required"] == ["summary", "llm_topics", "doc_type"]
    assert payload["messages"][0]["content"] == "Return valid JSON only."
    assert "JSON only: summary, llm_topics, doc_type" in payload["messages"][1]["content"]
    assert "summary, llm_topics, doc_type" in payload["messages"][1]["content"]
    assert "claims" not in payload["messages"][1]["content"]


def test_ollama_metadata_timeout_returns_specific_warning(monkeypatch) -> None:
    calls = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        raise ServiceRequestError("ollama", "request timed out")

    monkeypatch.setattr(ollama_module, "request_json", fake_request_json)
    client = OllamaClient(
        base_url="http://ollama:11434",
        chat_model="qwen3.5:27b",
        embed_model="nomic-embed-text:latest",
        timeout_seconds=45,
    )

    metadata = client.generate_metadata("document text")

    assert len(calls) == 1
    assert metadata["_warnings"] == ["ollama_metadata_timeout"]
    assert metadata["_metadata_errors"][0] == {
        "warning": "ollama_metadata_timeout",
        "service": "ollama",
        "attempts": 1,
        "message": "request timed out",
    }


def test_ollama_metadata_invalid_json_returns_specific_warning(monkeypatch) -> None:
    def fake_request_json(base_url, path, **kwargs):
        return {"message": {"content": "not-json"}}

    monkeypatch.setattr(ollama_module, "request_json", fake_request_json)
    client = OllamaClient(
        base_url="http://ollama:11434",
        chat_model="qwen3.5:27b",
        embed_model="nomic-embed-text:latest",
        timeout_seconds=45,
    )

    metadata = client.generate_metadata("document text")

    assert metadata["_warnings"] == ["ollama_metadata_invalid_json"]
    assert metadata["_metadata_errors"][0]["message"] == "metadata response was not valid JSON"


def test_ollama_metadata_http_error_returns_safe_diagnostic(monkeypatch) -> None:
    def fake_request_json(base_url, path, **kwargs):
        raise ServiceRequestError("ollama", "raw response with token=secret", status_code=500)

    monkeypatch.setattr(ollama_module, "request_json", fake_request_json)
    client = OllamaClient(
        base_url="http://ollama:11434",
        chat_model="qwen3.5:27b",
        embed_model="nomic-embed-text:latest",
        timeout_seconds=45,
    )

    metadata = client.generate_metadata("document text")

    assert metadata["_warnings"] == ["ollama_metadata_http_error"]
    assert metadata["_metadata_errors"][0] == {
        "warning": "ollama_metadata_http_error",
        "service": "ollama",
        "attempts": 1,
        "message": "metadata service returned HTTP 500",
        "status_code": 500,
    }
