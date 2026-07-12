"""Outbound runtime contract used by deployment application logic."""

from __future__ import annotations

from typing import Protocol

from .models import DeploymentRequest, RuntimeReadiness, ServiceStatus


class DeploymentRuntime(Protocol):
    """Inspect and reconfigure the selected deployment services."""

    def environment_matches(self, request: DeploymentRequest) -> bool: ...

    def service_statuses(self, services: tuple[str, ...]) -> tuple[ServiceStatus, ...]: ...

    def recreate(self, request: DeploymentRequest) -> tuple[ServiceStatus, ...]: ...

    def probe(self) -> RuntimeReadiness: ...
