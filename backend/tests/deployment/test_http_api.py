from __future__ import annotations

import json
from contextlib import contextmanager
from http.client import HTTPConnection
from threading import Thread
from typing import Any, Iterator, Literal

import pytest

from rag.deployment.http_api import DeploymentControllerServer, MAX_REQUEST_BYTES
from rag.deployment.models import (
    DeploymentRequest,
    DeploymentResult,
    RuntimeReadiness,
    ServiceStatus,
)
from rag.deployment.service import DeploymentBusyError


def test_apply_requires_dedicated_service_token() -> None:
    application = _Application()
    with _running_server(application) as port:
        status, payload = _post(port, _valid_payload(), token="wrong-token")

    assert status == 401
    assert payload == {"error": "unauthorized"}
    assert application.requests == []


def test_apply_rejects_invalid_and_oversized_json_boundaries() -> None:
    application = _Application()
    with _running_server(application) as port:
        invalid_status, invalid_payload = _post(port, {"services": ["vllm-text"]})
        oversized_status, oversized_payload = _post_raw(port, b"{" + b" " * MAX_REQUEST_BYTES + b"}")

    assert invalid_status == 400
    assert invalid_payload["error"] == "invalid_request"
    assert invalid_payload["message"] == "text limits are required."
    assert oversized_status == 400
    assert oversized_payload == {
        "error": "invalid_request",
        "message": "Request body must be JSON and no larger than 64 KiB.",
    }


def test_apply_returns_legacy_status_and_applied_outcome() -> None:
    application = _Application(result=_result("applied"))
    with _running_server(application) as port:
        status, payload = _post(port, _valid_payload())

    assert status == 200
    assert payload["status"] == "applied"
    assert payload["outcome"] == "applied"
    assert payload["message"].startswith("Recreated vllm-text")
    assert payload["services"] == [
        {"service": "vllm-text", "status": "running", "detail": "Up 2 seconds"}
    ]
    assert application.requests[0].services == ("vllm-text",)


def test_apply_returns_legacy_status_and_unchanged_outcome() -> None:
    application = _Application(result=_result("unchanged"))
    with _running_server(application) as port:
        status, payload = _post(port, _valid_payload())

    assert status == 200
    assert payload["status"] == "applied"
    assert payload["outcome"] == "unchanged"
    assert "No recreation was needed" in payload["message"]


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (DeploymentBusyError("busy"), 409, "deployment_busy"),
        (TimeoutError("too slow"), 504, "timeout"),
        (RuntimeError("compose failed"), 502, "compose_failed"),
    ],
)
def test_apply_maps_operational_failures(
    error: RuntimeError,
    expected_status: int,
    expected_code: str,
) -> None:
    application = _Application(apply_error=error)
    with _running_server(application) as port:
        status, payload = _post(port, _valid_payload())

    assert status == expected_status
    assert payload == {"error": expected_code, "message": str(error)}


@pytest.mark.parametrize(
    ("readiness", "expected_status", "expected_payload_status"),
    [
        (RuntimeReadiness(ready=True, detail="Docker daemon and Compose are available."), 200, "ok"),
        (RuntimeReadiness(ready=False, detail="Docker daemon unavailable."), 503, "unavailable"),
    ],
)
def test_readiness_reflects_runtime_probe(
    readiness: RuntimeReadiness,
    expected_status: int,
    expected_payload_status: str,
) -> None:
    application = _Application(readiness=readiness)
    with _running_server(application) as port:
        status, payload = _get(port, "/health/ready")

    assert status == expected_status
    assert payload == {"status": expected_payload_status, "detail": readiness.detail}
    assert application.readiness_calls == 1


def test_liveness_does_not_depend_on_runtime_readiness() -> None:
    application = _Application(readiness=RuntimeReadiness(ready=False, detail="unavailable"))
    with _running_server(application) as port:
        status, payload = _get(port, "/health/live")

    assert status == 200
    assert payload == {"status": "ok"}
    assert application.readiness_calls == 0


class _Application:
    def __init__(
        self,
        *,
        result: DeploymentResult | None = None,
        apply_error: RuntimeError | None = None,
        readiness: RuntimeReadiness | None = None,
    ) -> None:
        self.result = result or _result("applied")
        self.apply_error = apply_error
        self.runtime_readiness = readiness or RuntimeReadiness(ready=True, detail="ready")
        self.requests: list[DeploymentRequest] = []
        self.readiness_calls = 0

    def apply(self, request: DeploymentRequest) -> DeploymentResult:
        self.requests.append(request)
        if self.apply_error is not None:
            raise self.apply_error
        return self.result

    def readiness(self) -> RuntimeReadiness:
        self.readiness_calls += 1
        return self.runtime_readiness


@contextmanager
def _running_server(application: _Application) -> Iterator[int]:
    server = DeploymentControllerServer(
        ("127.0.0.1", 0),
        application=application,
        token="controller-secret",
        allowed_services={"vllm-text", "vllm-embeddings", "vllm-vision"},
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _post(port: int, payload: dict[str, Any], *, token: str = "controller-secret") -> tuple[int, dict[str, Any]]:
    return _post_raw(port, json.dumps(payload).encode(), token=token)


def _post_raw(
    port: int,
    body: bytes,
    *,
    token: str = "controller-secret",
) -> tuple[int, dict[str, Any]]:
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    connection.request(
        "POST",
        "/v1/vllm/apply",
        body=body,
        headers={
            "Content-Type": "application/json",
            "X-Service-Token": token,
        },
    )
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def _get(port: int, path: str) -> tuple[int, dict[str, Any]]:
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    connection.request("GET", path)
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def _valid_payload() -> dict[str, Any]:
    return {
        "services": ["vllm-text"],
        "text": {
            "max_model_len": 4096,
            "gpu_memory_utilization": 0.25,
            "kv_cache_memory_bytes": "2G",
            "max_num_seqs": 2,
            "max_num_batched_tokens": 4096,
        },
    }


def _result(outcome: Literal["applied", "unchanged"]) -> DeploymentResult:
    return DeploymentResult(
        outcome=outcome,
        services=(ServiceStatus(service="vllm-text", status="running", detail="Up 2 seconds"),),
    )
