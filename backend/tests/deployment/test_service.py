from __future__ import annotations

from threading import Event, Thread

import pytest

from rag.deployment.models import (
    DeploymentRequest,
    RuntimeReadiness,
    ServiceDeployment,
    ServiceStatus,
)
from rag.deployment.service import DeploymentBusyError, DeploymentService


def test_apply_recreates_services_when_environment_changed() -> None:
    runtime = _FakeRuntime(matches=False)

    result = DeploymentService(runtime).apply(_request())

    assert result.outcome == "applied"
    assert result.services == runtime.statuses
    assert runtime.recreate_calls == 1


def test_apply_is_noop_when_running_environment_is_identical() -> None:
    runtime = _FakeRuntime(matches=True)

    result = DeploymentService(runtime).apply(_request())

    assert result.outcome == "unchanged"
    assert result.services == runtime.statuses
    assert runtime.recreate_calls == 0
    assert runtime.status_calls == 1


def test_overlapping_apply_is_rejected_as_busy() -> None:
    runtime = _BlockingRuntime()
    service = DeploymentService(runtime)
    first_error: list[BaseException] = []

    def apply_first_request() -> None:
        try:
            service.apply(_request())
        except BaseException as exc:  # pragma: no cover - captured for the main test thread
            first_error.append(exc)

    thread = Thread(target=apply_first_request)
    thread.start()
    assert runtime.entered.wait(timeout=1)
    try:
        with pytest.raises(DeploymentBusyError, match="already in progress"):
            service.apply(_request())
    finally:
        runtime.release.set()
        thread.join(timeout=1)

    assert not thread.is_alive()
    assert first_error == []
    assert runtime.recreate_calls == 1


def test_readiness_delegates_to_runtime_probe() -> None:
    runtime = _FakeRuntime(matches=True)

    readiness = DeploymentService(runtime).readiness()

    assert readiness == RuntimeReadiness(ready=True, detail="ready")


class _FakeRuntime:
    def __init__(self, *, matches: bool) -> None:
        self.matches = matches
        self.statuses = (ServiceStatus(service="vllm-text", status="running", detail="Up"),)
        self.recreate_calls = 0
        self.status_calls = 0

    def environment_matches(self, request: DeploymentRequest) -> bool:
        assert request == _request()
        return self.matches

    def service_statuses(self, services: tuple[str, ...]) -> tuple[ServiceStatus, ...]:
        assert services == ("vllm-text",)
        self.status_calls += 1
        return self.statuses

    def recreate(self, request: DeploymentRequest) -> tuple[ServiceStatus, ...]:
        assert request == _request()
        self.recreate_calls += 1
        return self.statuses

    def probe(self) -> RuntimeReadiness:
        return RuntimeReadiness(ready=True, detail="ready")


class _BlockingRuntime(_FakeRuntime):
    def __init__(self) -> None:
        super().__init__(matches=False)
        self.entered = Event()
        self.release = Event()

    def environment_matches(self, request: DeploymentRequest) -> bool:
        assert request == _request()
        self.entered.set()
        assert self.release.wait(timeout=1)
        return False


def _request() -> DeploymentRequest:
    return DeploymentRequest(
        deployments=(
            ServiceDeployment(
                service="vllm-text",
                environment=(("VLLM_TEXT_MAX_MODEL_LEN", "4096"),),
            ),
        )
    )

