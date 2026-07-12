"""Docker Compose runtime adapter for deployment-controller operations."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..models import DeploymentRequest, RuntimeReadiness, ServiceStatus
from ..validation import DEFAULT_SERVICES, SERVICE_LIMITS

LOGGER = logging.getLogger(__name__)
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
VLLM_CACHE_ENV = "VLLM_CACHE_HOST_DIR"
VLLM_CACHE_CONTAINER_PATH = "/models"
ENVIRONMENT_ARGUMENTS = {
    environment_name: f"--{field.replace('_', '-')}"
    for _, environment_names in SERVICE_LIMITS.values()
    for field, environment_name in environment_names.items()
}


class DockerComposeTimeoutError(TimeoutError):
    """Docker Compose exceeded the configured apply timeout."""


class DockerComposeError(RuntimeError):
    """Docker Compose could not apply the requested services."""


@dataclass(frozen=True)
class DockerComposeConfig:
    compose_file: str = "/workspace/docker-compose.yml"
    project_dir: str = "/workspace"
    project_name: str = "agenticrag"
    timeout_seconds: int = 900
    status_delay_seconds: float = 2.0

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> DockerComposeConfig:
        source = os.environ if environment is None else environment
        return cls(
            compose_file=source.get("DEPLOYMENT_COMPOSE_FILE", "/workspace/docker-compose.yml"),
            project_dir=source.get("DEPLOYMENT_COMPOSE_PROJECT_DIR", "/workspace"),
            project_name=source.get("DEPLOYMENT_COMPOSE_PROJECT_NAME", "agenticrag"),
            timeout_seconds=int(source.get("DEPLOYMENT_COMPOSE_TIMEOUT_SECONDS", "900")),
            status_delay_seconds=float(source.get("DEPLOYMENT_STATUS_DELAY_SECONDS", "2")),
        )


class DockerComposeRuntime:
    """Inspect and recreate allowlisted vLLM services with Docker Compose."""

    def __init__(
        self,
        config: DockerComposeConfig,
        *,
        environment: Mapping[str, str] | None = None,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._environment = dict(os.environ if environment is None else environment)
        self._run_command = run_command
        self._sleep = sleep

    def probe(self) -> RuntimeReadiness:
        compose = self._run_probe(["docker", "compose", "version", "--short"])
        if compose is not None:
            return compose
        docker = self._run_probe(["docker", "info", "--format", "{{.ServerVersion}}"])
        if docker is not None:
            return docker
        return RuntimeReadiness(ready=True, detail="Docker daemon and Compose are available.")

    def environment_matches(self, request: DeploymentRequest) -> bool:
        for deployment in request.deployments:
            container_id = self._service_container_id(deployment.service, include_stopped=False)
            if not container_id:
                return False
            current = self._container_configuration(container_id)
            if current is None:
                return False
            environment, command = current
            expected = dict(deployment.environment)
            managed_names = set(SERVICE_LIMITS[deployment.service][1].values())
            if set(expected) != managed_names:
                return False
            if any(
                environment.get(name, _argument_value(command, ENVIRONMENT_ARGUMENTS[name])) != value
                for name, value in expected.items()
            ):
                return False
        return True

    def service_statuses(self, services: tuple[str, ...]) -> tuple[ServiceStatus, ...]:
        return tuple(self._service_status(service) for service in services)

    def recreate(self, request: DeploymentRequest) -> tuple[ServiceStatus, ...]:
        command = [
            "docker",
            "compose",
            "-p",
            self._config.project_name,
            "-f",
            self._config.compose_file,
            "up",
            "-d",
            "--force-recreate",
            "--no-deps",
            *request.services,
        ]
        environment = self._environment.copy()
        environment.update(request.environment)
        self._reuse_existing_vllm_cache_bind(environment, request.services)
        try:
            completed = self._run_command(
                command,
                cwd=self._config.project_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self._config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerComposeTimeoutError(
                f"Docker Compose did not finish within {self._config.timeout_seconds} seconds."
            ) from exc
        except OSError as exc:
            raise DockerComposeError(f"Docker Compose could not be started: {exc}") from exc
        if completed.returncode != 0:
            raise DockerComposeError(_format_process_error(completed))
        self._sleep(self._config.status_delay_seconds)
        return self.service_statuses(request.services)

    def _run_probe(self, command: list[str]) -> RuntimeReadiness | None:
        try:
            completed = self._run_command(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RuntimeReadiness(ready=False, detail=f"Deployment runtime probe failed: {exc}")
        if completed.returncode != 0:
            detail = _truncate(completed.stderr.strip() or completed.stdout.strip())
            return RuntimeReadiness(
                ready=False,
                detail=f"Deployment runtime probe failed: {detail or f'exit code {completed.returncode}'}",
            )
        return None

    def _reuse_existing_vllm_cache_bind(
        self,
        environment: dict[str, str],
        services: tuple[str, ...],
    ) -> None:
        configured = environment.get(VLLM_CACHE_ENV, "")
        if configured:
            configured_source = _compose_bind_source(configured)
            if _is_compose_absolute_path(configured_source):
                environment[VLLM_CACHE_ENV] = configured_source
                return
        source = self._existing_mount_source(services, VLLM_CACHE_CONTAINER_PATH)
        if source:
            environment[VLLM_CACHE_ENV] = _compose_bind_source(source)

    def _existing_mount_source(self, services: tuple[str, ...], destination: str) -> str | None:
        candidates = (*services, *(service for service in DEFAULT_SERVICES if service not in services))
        for service in candidates:
            container_id = self._service_container_id(service, include_stopped=True)
            if not container_id:
                continue
            source = self._container_mount_source(container_id, destination)
            if source:
                return source
        return None

    def _service_container_id(self, service: str, *, include_stopped: bool) -> str | None:
        command = ["docker", "ps"]
        if include_stopped:
            command.append("-a")
        command.extend(
            [
                "--filter",
                f"label=com.docker.compose.project={self._config.project_name}",
                "--filter",
                f"label=com.docker.compose.service={service}",
                "--format",
                "{{.ID}}",
            ]
        )
        completed = self._inspect_command(command, purpose=f"locate service {service}")
        if completed is None or not completed.stdout.strip():
            return None
        return completed.stdout.strip().splitlines()[0]

    def _container_configuration(
        self,
        container_id: str,
    ) -> tuple[dict[str, str], tuple[str, ...]] | None:
        completed = self._inspect_command(
            [
                "docker",
                "inspect",
                container_id,
                "--format",
                "{{json .Config}}",
            ],
            purpose="inspect container configuration",
        )
        if completed is None or not completed.stdout.strip():
            return None
        try:
            configuration = json.loads(completed.stdout)
        except json.JSONDecodeError:
            LOGGER.warning("Docker returned invalid JSON while inspecting container configuration.")
            return None
        if not isinstance(configuration, dict):
            LOGGER.warning("Docker returned an invalid container configuration payload.")
            return None
        entries = configuration.get("Env")
        command = configuration.get("Cmd")
        if (
            not isinstance(entries, list)
            or not all(isinstance(entry, str) for entry in entries)
            or not isinstance(command, list)
            or not all(isinstance(argument, str) for argument in command)
        ):
            LOGGER.warning("Docker returned an invalid container configuration payload.")
            return None
        environment = dict(entry.split("=", 1) for entry in entries if "=" in entry)
        return environment, tuple(command)

    def _container_mount_source(self, container_id: str, destination: str) -> str | None:
        completed = self._inspect_command(
            ["docker", "inspect", container_id, "--format", "{{json .Mounts}}"],
            purpose="inspect container mounts",
        )
        if completed is None or not completed.stdout.strip():
            return None
        try:
            mounts = json.loads(completed.stdout)
        except json.JSONDecodeError:
            LOGGER.warning("Docker returned invalid JSON while inspecting container mounts.")
            return None
        if not isinstance(mounts, list):
            LOGGER.warning("Docker returned an invalid container mounts payload.")
            return None
        for mount in mounts:
            if not isinstance(mount, dict):
                continue
            if mount.get("Type") == "bind" and mount.get("Destination") == destination:
                source = mount.get("Source")
                if isinstance(source, str) and source.strip():
                    return source.strip()
        return None

    def _service_status(self, service: str) -> ServiceStatus:
        command = [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={self._config.project_name}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.Names}}\t{{.Status}}",
        ]
        try:
            completed = self._run_command(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ServiceStatus(
                service=service,
                status="unknown",
                detail=f"Docker status check could not be completed: {exc}",
            )
        if completed.returncode != 0:
            return ServiceStatus(service=service, status="unknown", detail=_truncate(completed.stderr))
        line = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
        if not line:
            return ServiceStatus(service=service, status="not_found", detail="No running container found.")
        parts = line.split("\t", 1)
        return ServiceStatus(
            service=service,
            status="running",
            detail=parts[1] if len(parts) > 1 else parts[0],
        )

    def _inspect_command(
        self,
        command: list[str],
        *,
        purpose: str,
    ) -> subprocess.CompletedProcess[str] | None:
        try:
            completed = self._run_command(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            LOGGER.warning("Could not %s: %s", purpose, exc)
            return None
        if completed.returncode != 0:
            LOGGER.warning("Could not %s: %s", purpose, _truncate(completed.stderr.strip()))
            return None
        return completed


def _compose_bind_source(source: str) -> str:
    normalized = source.strip()
    if WINDOWS_ABSOLUTE_PATH_PATTERN.match(normalized):
        drive = normalized[0].lower()
        rest = normalized[2:].replace("\\", "/").lstrip("/")
        return f"/run/desktop/mnt/host/{drive}/{rest}"
    return normalized


def _is_compose_absolute_path(value: str) -> bool:
    normalized = value.strip()
    return os.path.isabs(normalized) or normalized.startswith("\\\\")


def _format_process_error(completed: subprocess.CompletedProcess[str]) -> str:
    stderr = _truncate(completed.stderr.strip())
    stdout = _truncate(completed.stdout.strip())
    if stderr and stdout:
        return f"Docker Compose failed: {stderr} | {stdout}"
    return f"Docker Compose failed: {stderr or stdout or f'exit code {completed.returncode}'}"


def _argument_value(command: tuple[str, ...], argument: str) -> str | None:
    try:
        position = command.index(argument)
    except ValueError:
        return None
    value_position = position + 1
    return command[value_position] if value_position < len(command) else None


def _truncate(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else f"{value[:limit]}..."
