"""Application service for serialized, idempotent deployment changes."""

from __future__ import annotations

from threading import Lock

from .models import DeploymentRequest, DeploymentResult, RuntimeReadiness
from .ports import DeploymentRuntime


class DeploymentBusyError(RuntimeError):
    """Another apply operation is already active in this controller process."""


class DeploymentService:
    """Serialize and apply deployment requests through a runtime adapter."""

    def __init__(self, runtime: DeploymentRuntime) -> None:
        self._runtime = runtime
        self._apply_lock = Lock()

    def apply(self, request: DeploymentRequest) -> DeploymentResult:
        if not self._apply_lock.acquire(blocking=False):
            raise DeploymentBusyError("Another deployment apply operation is already in progress.")
        try:
            if self._runtime.environment_matches(request):
                return DeploymentResult(
                    outcome="unchanged",
                    services=self._runtime.service_statuses(request.services),
                )
            return DeploymentResult(
                outcome="applied",
                services=self._runtime.recreate(request),
            )
        finally:
            self._apply_lock.release()

    def readiness(self) -> RuntimeReadiness:
        return self._runtime.probe()
