"""Immutable commands and results for deployment operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ServiceDeployment:
    """The managed environment requested for one Compose service."""

    service: str
    environment: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DeploymentRequest:
    """A validated request to apply launch limits to selected services."""

    deployments: tuple[ServiceDeployment, ...]

    @property
    def services(self) -> tuple[str, ...]:
        return tuple(deployment.service for deployment in self.deployments)

    @property
    def environment(self) -> dict[str, str]:
        return {
            name: value
            for deployment in self.deployments
            for name, value in deployment.environment
        }


@dataclass(frozen=True)
class ServiceStatus:
    """Observable runtime state for one managed service."""

    service: str
    status: Literal["running", "not_found", "unknown"]
    detail: str


@dataclass(frozen=True)
class DeploymentResult:
    """The outcome of applying an already validated deployment request."""

    outcome: Literal["applied", "unchanged"]
    services: tuple[ServiceStatus, ...]


@dataclass(frozen=True)
class RuntimeReadiness:
    """Whether the controller can reach its required deployment runtime."""

    ready: bool
    detail: str
