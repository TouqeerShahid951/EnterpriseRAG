from __future__ import annotations

import pytest

from rag.query.configuration import service as rag_config_service
from rag.query.configuration.models import RagConfigRecord


@pytest.mark.parametrize(
    ("model", "expects_format"),
    (
        ("qwen3.5:cloud", False),
        ("gemma4:31b-cloud", False),
        ("qwen3.5:9b", True),
        ("qwen3.5:cloud-preview", True),
    ),
)
def test_ollama_chat_probe_only_omits_format_for_exact_cloud_suffix(
    monkeypatch,
    model: str,
    expects_format: bool,
) -> None:
    calls = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {"message": {"content": '{"status":"ok"}'}}

    monkeypatch.setattr(rag_config_service, "request_json", fake_request_json)
    config_record = RagConfigRecord(
        provider="ollama",
        embedding_provider="fastembed",
        base_url="http://ollama:11434",
        embedding_base_url="http://ollama:11434",
        chat_model="qwen3.5:9b",
        embed_model="nomic-ai/nomic-embed-text-v1.5-Q",
        faithfulness_model=None,
        chat_timeout_seconds=180,
        embed_timeout_seconds=45,
    )

    rag_config_service._ollama_chat_probe(config_record, model=model)

    payload = calls[0][2]["payload"]
    assert payload["model"] == model
    assert ("format" in payload) is expects_format
    assert payload["messages"][0]["content"].endswith("Return JSON only.")
    assert payload["messages"][1]["content"] == 'Return {"status":"ok"}.'
