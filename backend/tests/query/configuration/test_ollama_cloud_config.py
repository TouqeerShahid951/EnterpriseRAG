from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag.query.configuration import service as rag_config_service
from rag.query.configuration.models import RagConfigRecord
from rag.query.configuration.service import RagConfigValidationError


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
    rag_config_service._ollama_chat_probe(_config_record(), model=model)

    payload = calls[0][2]["payload"]
    assert payload["model"] == model
    assert ("format" in payload) is expects_format
    assert payload["messages"][0]["content"].endswith("Return JSON only.")
    assert payload["messages"][1]["content"] == 'Return {"status":"ok"}.'


def test_structured_output_probe_rejects_cloud_before_request(monkeypatch) -> None:
    called = False

    def fake_request_json(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"message": {"content": '{"status":"ok"}'}}

    monkeypatch.setattr(rag_config_service, "request_json", fake_request_json)

    with pytest.raises(
        RagConfigValidationError,
        match="does not support schema-constrained output",
    ):
        rag_config_service._ollama_chat_probe(
            _config_record(),
            model="nemotron-3-super:cloud",
            structured_output=True,
        )

    assert called is False


def test_structured_output_probe_sends_schema_to_local_model(monkeypatch) -> None:
    calls = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {"message": {"content": '{"status":"ok"}'}}

    monkeypatch.setattr(rag_config_service, "request_json", fake_request_json)

    rag_config_service._ollama_chat_probe(
        _config_record(),
        model="qwen3:8b",
        structured_output=True,
    )

    schema = calls[0][2]["payload"]["format"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["status"]["enum"] == ["ok"]


def test_validation_schema_probes_evaluation_verifier_model_override(
    monkeypatch,
) -> None:
    config = _config_record()
    role_probes = []

    monkeypatch.setattr(rag_config_service, "_reranker_probe", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        rag_config_service,
        "list_runtime_models",
        lambda _config: (
            [config.chat_model],
            [config.embed_model],
            {
                role: [config.chat_model, "verifier-local"]
                for role in ("reasoning", "routing", "faithfulness", "ingestion", "vision")
            },
        ),
    )
    monkeypatch.setattr(rag_config_service, "_chat_probe", lambda _config: None)
    monkeypatch.setattr(
        rag_config_service,
        "_role_probe",
        lambda _config, role, model: role_probes.append((role, model)),
    )
    monkeypatch.setattr(
        rag_config_service,
        "_embedding_dimension",
        lambda *_args, **_kwargs: 768,
    )
    monkeypatch.setattr(
        rag_config_service,
        "_qdrant_vector_size",
        lambda *_args, **_kwargs: None,
    )

    rag_config_service.validate_rag_config(
        config,
        app_config=SimpleNamespace(
            evaluation_answer_llm_verifier_enabled=True,
            evaluation_answer_llm_verifier_model="verifier-local",
        ),
    )

    assert role_probes[:2] == [
        ("reasoning", config.chat_model),
        ("reasoning", "verifier-local"),
    ]


def _config_record() -> RagConfigRecord:
    return RagConfigRecord(
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
