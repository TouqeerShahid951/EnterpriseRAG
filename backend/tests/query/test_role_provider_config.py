from __future__ import annotations

from rag.core.config import Settings
from rag.query import ollama as query_ollama
from rag.query import openai_compatible as query_openai
from rag.query.inference import build_inference_client
from rag.query.http import ServiceRequestError
from rag.query.rag_config_service import discover_runtime_models, list_runtime_models
from rag.repositories.rag_config_models import RagConfigRecord
from rag.repositories.rag_config_validation import env_rag_config


class _Settings:
    rag_http_timeout_seconds = 45
    rag_dense_cache_dir = "/models/fastembed"
    ollama_num_ctx = 16384


def test_env_rag_config_supports_mixed_role_providers() -> None:
    record = env_rag_config(
        Settings(
            rag_model_provider="vllm",
            rag_chat_provider="vllm",
            rag_embedding_provider="fastembed",
            vllm_base_url="http://vllm-text:8000/v1",
            vllm_chat_model="Qwen/Qwen3-14B-AWQ",
            rag_ingestion_provider="ollama",
            rag_vision_provider="ollama",
            ollama_base_url="http://host.docker.internal:11434",
            rag_ingestion_model="qwen3:14b",
            ollama_vision_model="qwen2.5vl:3b",
        )
    )

    assert record.provider == "vllm"
    assert record.chat_model == "Qwen/Qwen3-14B-AWQ"
    assert record.effective_ingestion_provider == "ollama"
    assert record.effective_ingestion_base_url == "http://host.docker.internal:11434"
    assert record.effective_vision_provider == "ollama"
    assert record.effective_vision_base_url == "http://host.docker.internal:11434"
    assert record.ingestion_model == "qwen3:14b"
    assert record.vision_model == "qwen2.5vl:3b"


def test_list_runtime_models_queries_each_provider_endpoint(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs.get("service", "")))
        if path == "/v1/models":
            return {"data": [{"id": "Qwen/Qwen3-14B-AWQ"}]}
        if path == "/api/tags":
            return {"models": [{"name": "qwen3:14b"}, {"name": "qwen2.5vl:3b"}]}
        raise AssertionError(f"unexpected request: {base_url} {path}")

    monkeypatch.setattr("rag.query.rag_config_service.request_json", fake_request_json)
    monkeypatch.setattr(
        "rag.query.rag_config_service.list_supported_dense_models",
        lambda: ["nomic-ai/nomic-embed-text-v1.5-Q"],
    )

    chat_models, embedding_models, role_models = list_runtime_models(
        RagConfigRecord(
            provider="vllm",
            embedding_provider="fastembed",
            ingestion_provider="ollama",
            vision_provider="ollama",
            base_url="http://vllm-text:8000",
            ingestion_base_url="http://ollama:11434",
            vision_base_url="http://ollama:11434",
            embedding_base_url="http://vllm-text:8000",
            chat_model="Qwen/Qwen3-14B-AWQ",
            embed_model="nomic-ai/nomic-embed-text-v1.5-Q",
            faithfulness_model=None,
            chat_timeout_seconds=180,
            embed_timeout_seconds=45,
        )
    )

    assert chat_models == ["Qwen/Qwen3-14B-AWQ"]
    assert embedding_models == ["nomic-ai/nomic-embed-text-v1.5-Q"]
    assert role_models["ingestion"] == ["qwen2.5vl:3b", "qwen3:14b"]
    assert role_models["vision"] == ["qwen2.5vl:3b", "qwen3:14b"]
    assert ("http://vllm-text:8000", "/v1/models", "vllm_chat") in calls
    assert ("http://ollama:11434", "/api/tags", "ollama_ingestion") in calls


def test_discover_runtime_models_keeps_healthy_roles_when_one_endpoint_fails(monkeypatch) -> None:
    def fake_request_json(base_url, path, **kwargs):
        if base_url == "http://vllm-text:8000" and path == "/v1/models":
            return {"data": [{"id": "Qwen/Qwen3-14B-AWQ"}]}
        if base_url == "http://vllm-vision:8000" and path == "/v1/models":
            raise ServiceRequestError(kwargs.get("service", "vllm_vision"), "connection refused")
        raise AssertionError(f"unexpected request: {base_url} {path}")

    monkeypatch.setattr("rag.query.rag_config_service.request_json", fake_request_json)
    monkeypatch.setattr(
        "rag.query.rag_config_service.list_supported_dense_models",
        lambda: ["nomic-ai/nomic-embed-text-v1.5-Q"],
    )

    result = discover_runtime_models(
        RagConfigRecord(
            provider="vllm",
            embedding_provider="fastembed",
            reasoning_provider="vllm",
            routing_provider="vllm",
            faithfulness_provider="vllm",
            ingestion_provider="vllm",
            vision_provider="vllm",
            base_url="http://vllm-text:8000",
            vision_base_url="http://vllm-vision:8000",
            embedding_base_url="http://vllm-text:8000",
            chat_model="Qwen/Qwen3-14B-AWQ",
            embed_model="nomic-ai/nomic-embed-text-v1.5-Q",
            chat_timeout_seconds=180,
            embed_timeout_seconds=45,
        )
    )

    assert result.chat_models == ["Qwen/Qwen3-14B-AWQ"]
    assert result.role_models["reasoning"] == ["Qwen/Qwen3-14B-AWQ"]
    assert result.role_models["vision"] == []
    assert result.embedding_models == ["nomic-ai/nomic-embed-text-v1.5-Q"]
    assert result.statuses["chat"].status == "ok"
    assert result.statuses["vision"].status == "error"
    assert "connection refused" in result.statuses["vision"].message


def test_build_inference_client_routes_chat_and_routing_to_configured_providers(monkeypatch) -> None:
    openai_calls = []
    ollama_calls = []

    def fake_openai_request_json(base_url, path, **kwargs):
        openai_calls.append((base_url, path, kwargs))
        return {"choices": [{"message": {"content": "answer"}}]}

    def fake_ollama_request_json(base_url, path, **kwargs):
        ollama_calls.append((base_url, path, kwargs))
        return {"message": {"content": '{"status":"ok"}'}}

    monkeypatch.setattr(query_openai, "request_json", fake_openai_request_json)
    monkeypatch.setattr(query_ollama, "request_json", fake_ollama_request_json)

    client = build_inference_client(
        RagConfigRecord(
            provider="vllm",
            routing_provider="ollama",
            embedding_provider="ollama",
            base_url="http://vllm-text:8000",
            routing_base_url="http://ollama-route:11434",
            embedding_base_url="http://ollama-embed:11434",
            chat_model="Qwen/Qwen3-14B-AWQ",
            embed_model="nomic-embed-text:latest",
            routing_model="qwen3:14b",
            faithfulness_model=None,
            chat_timeout_seconds=180,
            embed_timeout_seconds=45,
        ),
        settings=_Settings(),  # type: ignore[arg-type]
    )

    assert client.answer(question="What?", contexts=["Evidence"]) == "answer"
    assert client.verify_route(prompt="route", model=None) == '{"status":"ok"}'
    assert openai_calls[0][0] == "http://vllm-text:8000"
    assert ollama_calls[0][0] == "http://ollama-route:11434"
    assert ollama_calls[0][2]["payload"]["model"] == "qwen3:14b"
