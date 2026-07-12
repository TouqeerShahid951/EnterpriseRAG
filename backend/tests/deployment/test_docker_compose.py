from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

from rag.deployment.adapters.docker_compose import (
    DockerComposeConfig,
    DockerComposeError,
    DockerComposeRuntime,
    DockerComposeTimeoutError,
)
from rag.deployment.models import DeploymentRequest, ServiceDeployment
from rag.deployment.service import DeploymentService


def test_runtime_recreates_service_with_requested_environment() -> None:
    runner = _ScriptedRunner()
    runner.responses.extend(
        [
            _completed(),
            _completed(stdout="agenticrag-vllm-text-1\tUp 3 seconds\n"),
        ]
    )
    runtime = _runtime(runner, environment={"VLLM_CACHE_HOST_DIR": "/host/cache"})

    result = runtime.recreate(_request())

    compose_call = runner.calls[0]
    assert compose_call[0] == [
        "docker",
        "compose",
        "-p",
        "agenticrag",
        "-f",
        "/workspace/docker-compose.yml",
        "up",
        "-d",
        "--force-recreate",
        "--no-deps",
        "vllm-text",
    ]
    assert compose_call[1]["cwd"] == "/workspace"
    assert compose_call[1]["env"]["VLLM_TEXT_MAX_MODEL_LEN"] == "4096"
    assert result[0].status == "running"


def test_service_skips_compose_when_running_container_environment_matches() -> None:
    runner = _ScriptedRunner()
    configuration = json.dumps(
        {
            "Env": [],
            "Cmd": [
                "model",
                "--max-model-len",
                "4096",
                "--gpu-memory-utilization",
                "0.25",
                "--kv-cache-memory-bytes",
                "2G",
                "--max-num-seqs",
                "2",
                "--max-num-batched-tokens",
                "4096",
            ],
        }
    )
    runner.responses.extend(
        [
            _completed(stdout="container-id\n"),
            _completed(stdout=f"{configuration}\n"),
            _completed(stdout="agenticrag-vllm-text-1\tUp 2 hours\n"),
        ]
    )

    result = DeploymentService(_runtime(runner)).apply(_request())

    assert result.outcome == "unchanged"
    assert not any(call[0][0:2] == ["docker", "compose"] and "up" in call[0] for call in runner.calls)


def test_recreate_reports_compose_process_failure() -> None:
    runner = _ScriptedRunner()
    runner.responses.append(
        _completed(returncode=1, stdout="partial output", stderr="daemon rejected request")
    )

    with pytest.raises(DockerComposeError, match="daemon rejected request.*partial output"):
        _runtime(runner, environment={"VLLM_CACHE_HOST_DIR": "/cache"}).recreate(_request())


def test_recreate_reports_compose_timeout() -> None:
    runner = _ScriptedRunner()
    runner.responses.append(subprocess.TimeoutExpired(cmd="docker compose", timeout=12))
    runtime = DockerComposeRuntime(
        DockerComposeConfig(timeout_seconds=12, status_delay_seconds=0),
        environment={"VLLM_CACHE_HOST_DIR": "/cache"},
        run_command=runner,
        sleep=lambda _: None,
    )

    with pytest.raises(DockerComposeTimeoutError, match="within 12 seconds"):
        runtime.recreate(_request())


def test_recreate_reuses_existing_windows_cache_mount_for_relative_configuration() -> None:
    runner = _ScriptedRunner()
    mounts = json.dumps(
        [
            {
                "Type": "bind",
                "Source": r"C:\Users\me\model-cache\vllm",
                "Destination": "/models",
            }
        ]
    )
    runner.responses.extend(
        [
            _completed(stdout="container-id\n"),
            _completed(stdout=f"{mounts}\n"),
            _completed(),
            _completed(stdout="agenticrag-vllm-text-1\tUp 1 second\n"),
        ]
    )

    _runtime(runner, environment={"VLLM_CACHE_HOST_DIR": "./model-cache/vllm"}).recreate(_request())

    compose_call = next(call for call in runner.calls if call[0][0:2] == ["docker", "compose"])
    assert compose_call[1]["env"]["VLLM_CACHE_HOST_DIR"] == (
        "/run/desktop/mnt/host/c/Users/me/model-cache/vllm"
    )


def test_probe_requires_both_compose_and_docker_daemon() -> None:
    ready_runner = _ScriptedRunner()
    ready_runner.responses.extend([_completed(stdout="2.29.0\n"), _completed(stdout="27.0.0\n")])
    failed_runner = _ScriptedRunner()
    failed_runner.responses.append(_completed(returncode=1, stderr="compose unavailable"))

    assert _runtime(ready_runner).probe().ready is True
    readiness = _runtime(failed_runner).probe()
    assert readiness.ready is False
    assert "compose unavailable" in readiness.detail


class _ScriptedRunner:
    def __init__(self) -> None:
        self.responses: list[subprocess.CompletedProcess[str] | BaseException] = []
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _runtime(
    runner: _ScriptedRunner,
    *,
    environment: dict[str, str] | None = None,
) -> DockerComposeRuntime:
    return DockerComposeRuntime(
        DockerComposeConfig(status_delay_seconds=0),
        environment=environment or {},
        run_command=runner,
        sleep=lambda _: None,
    )


def _request() -> DeploymentRequest:
    return DeploymentRequest(
        deployments=(
            ServiceDeployment(
                service="vllm-text",
                environment=(
                    ("VLLM_TEXT_MAX_MODEL_LEN", "4096"),
                    ("VLLM_TEXT_GPU_MEMORY_UTILIZATION", "0.25"),
                    ("VLLM_TEXT_KV_CACHE_MEMORY_BYTES", "2G"),
                    ("VLLM_TEXT_MAX_NUM_SEQS", "2"),
                    ("VLLM_TEXT_MAX_NUM_BATCHED_TOKENS", "4096"),
                ),
            ),
        )
    )


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr)
