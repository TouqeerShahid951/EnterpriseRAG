"""Deployment controller HTTP request contract tests."""

from __future__ import annotations

import json
from dataclasses import replace
from urllib import request as urlrequest

from rag.deployment.controller_client import HttpDeploymentControllerClient
from rag.query.vllm_config_repository import env_vllm_deployment_config


class Response:
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"message":"limits applied"}'


def test_client_sends_authenticated_controller_payload(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def urlopen(request: urlrequest.Request, *, timeout: float) -> Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(urlrequest, "urlopen", urlopen)
    record = env_vllm_deployment_config()
    record = replace(
        record,
        text=replace(record.text, kv_cache_memory_bytes=None),
    )

    message = HttpDeploymentControllerClient(
        base_url="http://controller.example/",
        token_header="X-Service-Token",
        token="test-secret",
        timeout_seconds=930.0,
    ).apply(record, services=["vllm-text", "vllm-vision"])

    request = captured["request"]
    assert isinstance(request, urlrequest.Request)
    assert request.full_url == "http://controller.example/v1/vllm/apply"
    assert request.method == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("X-service-token") == "test-secret"
    assert captured["timeout"] == 930.0
    assert json.loads(request.data or b"{}") == {
        "services": ["vllm-text", "vllm-vision"],
        "text": {
            "max_model_len": record.text.max_model_len,
            "gpu_memory_utilization": (
                record.text.gpu_memory_utilization
            ),
            "max_num_seqs": record.text.max_num_seqs,
            "max_num_batched_tokens": (
                record.text.max_num_batched_tokens
            ),
        },
        "embeddings": {
            "max_model_len": record.embeddings.max_model_len,
            "gpu_memory_utilization": (
                record.embeddings.gpu_memory_utilization
            ),
            "max_num_seqs": record.embeddings.max_num_seqs,
            "max_num_batched_tokens": (
                record.embeddings.max_num_batched_tokens
            ),
        },
        "vision": {
            "max_model_len": record.vision.max_model_len,
            "gpu_memory_utilization": (
                record.vision.gpu_memory_utilization
            ),
            "max_num_seqs": record.vision.max_num_seqs,
            "max_num_batched_tokens": (
                record.vision.max_num_batched_tokens
            ),
            "kv_cache_memory_bytes": record.vision.kv_cache_memory_bytes,
        },
    }
    assert message == "limits applied"
