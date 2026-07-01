from __future__ import annotations

import json
import os
import re
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SERVICE_LIMITS = {
    "vllm-text": {
        "payload_key": "text",
        "env": {
            "max_model_len": "VLLM_TEXT_MAX_MODEL_LEN",
            "gpu_memory_utilization": "VLLM_TEXT_GPU_MEMORY_UTILIZATION",
            "kv_cache_memory_bytes": "VLLM_TEXT_KV_CACHE_MEMORY_BYTES",
            "max_num_seqs": "VLLM_TEXT_MAX_NUM_SEQS",
            "max_num_batched_tokens": "VLLM_TEXT_MAX_NUM_BATCHED_TOKENS",
        },
    },
    "vllm-embeddings": {
        "payload_key": "embeddings",
        "env": {
            "max_model_len": "VLLM_EMBED_MAX_MODEL_LEN",
            "gpu_memory_utilization": "VLLM_EMBED_GPU_MEMORY_UTILIZATION",
            "max_num_seqs": "VLLM_EMBED_MAX_NUM_SEQS",
            "max_num_batched_tokens": "VLLM_EMBED_MAX_NUM_BATCHED_TOKENS",
        },
    },
    "vllm-vision": {
        "payload_key": "vision",
        "env": {
            "max_model_len": "VLLM_VISION_MAX_MODEL_LEN",
            "gpu_memory_utilization": "VLLM_VISION_GPU_MEMORY_UTILIZATION",
            "kv_cache_memory_bytes": "VLLM_VISION_KV_CACHE_MEMORY_BYTES",
            "max_num_seqs": "VLLM_VISION_MAX_NUM_SEQS",
            "max_num_batched_tokens": "VLLM_VISION_MAX_NUM_BATCHED_TOKENS",
        },
    },
}

KV_CACHE_PATTERN = re.compile(r"^[1-9][0-9]*(B|K|M|G|T|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?$")
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
VLLM_CACHE_ENV = "VLLM_CACHE_HOST_DIR"
VLLM_CACHE_CONTAINER_PATH = "/models"


class DeploymentControllerHandler(BaseHTTPRequestHandler):
    server_version = "AgenticRAGDeploymentController/1.0"

    def do_GET(self) -> None:
        if self.path in {"/health/live", "/health/ready"}:
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/vllm/apply":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        try:
            payload = self._read_json()
            services = _requested_services(payload)
            env_overrides = _env_overrides(payload, services)
            result = _recreate_services(services, env_overrides)
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": str(exc)})
            return
        except TimeoutError as exc:
            self._json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "timeout", "message": str(exc)})
            return
        except RuntimeError as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": "compose_failed", "message": str(exc)})
            return

        self._json(
            HTTPStatus.OK,
            {
                "status": "applied",
                "message": (
                    f"Recreated {_service_message(services)} with the requested launch limits. "
                    "Model health may stay starting while weights load."
                ),
                "services": result,
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def _authorized(self) -> bool:
        expected = os.environ.get("DEPLOYMENT_CONTROLLER_TOKEN", "")
        if not expected:
            return False
        return self.headers.get("X-Service-Token") == expected

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 65536:
            raise ValueError("Request body must be JSON and no larger than 64 KiB.")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body is not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object.")
        return parsed

    def _json(self, status_code: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _requested_services(payload: dict[str, Any]) -> list[str]:
    allowed = {
        value.strip()
        for value in os.environ.get("DEPLOYMENT_ALLOWED_SERVICES", "vllm-text,vllm-embeddings,vllm-vision").split(",")
        if value.strip()
    }
    raw_services = payload.get("services") or ["vllm-text", "vllm-embeddings", "vllm-vision"]
    if not isinstance(raw_services, list) or not raw_services:
        raise ValueError("services must be a non-empty list.")
    services = [str(service) for service in raw_services]
    blocked = [service for service in services if service not in allowed or service not in SERVICE_LIMITS]
    if blocked:
        raise ValueError(f"Requested services are not allowlisted: {', '.join(blocked)}")
    return services


def _env_overrides(payload: dict[str, Any], services: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for service in services:
        service_config = SERVICE_LIMITS[service]
        key = service_config["payload_key"]
        limits = payload.get(key)
        if not isinstance(limits, dict):
            raise ValueError(f"{key} limits are required.")
        normalized = _validate_limits(key, limits)
        for field, env_name in service_config["env"].items():
            value = normalized.get(field)
            if value is not None:
                overrides[env_name] = str(value)
    return overrides


def _validate_limits(key: str, limits: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "max_model_len": _int_range(limits.get("max_model_len"), 256, 262144, f"{key}.max_model_len"),
        "gpu_memory_utilization": _float_range(
            limits.get("gpu_memory_utilization"),
            0.0,
            1.0,
            f"{key}.gpu_memory_utilization",
            exclusive_min=True,
        ),
        "max_num_seqs": _int_range(limits.get("max_num_seqs"), 1, 1024, f"{key}.max_num_seqs"),
        "max_num_batched_tokens": _int_range(
            limits.get("max_num_batched_tokens"),
            256,
            262144,
            f"{key}.max_num_batched_tokens",
        ),
    }
    kv_cache_memory_bytes = limits.get("kv_cache_memory_bytes")
    if kv_cache_memory_bytes is not None:
        value = str(kv_cache_memory_bytes).strip()
        if not KV_CACHE_PATTERN.match(value):
            raise ValueError(f"{key}.kv_cache_memory_bytes is not a valid byte-size value.")
        normalized["kv_cache_memory_bytes"] = value
    return normalized


def _int_range(value: Any, minimum: int, maximum: int, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    return parsed


def _float_range(value: Any, minimum: float, maximum: float, field: str, *, exclusive_min: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number.") from exc
    if (parsed <= minimum if exclusive_min else parsed < minimum) or parsed > maximum:
        lower = f"greater than {minimum}" if exclusive_min else f"at least {minimum}"
        raise ValueError(f"{field} must be {lower} and no more than {maximum}.")
    return parsed


def _recreate_services(services: list[str], env_overrides: dict[str, str]) -> list[dict[str, str]]:
    compose_file = os.environ.get("DEPLOYMENT_COMPOSE_FILE", "/workspace/docker-compose.yml")
    project_dir = os.environ.get("DEPLOYMENT_COMPOSE_PROJECT_DIR", "/workspace")
    project_name = os.environ.get("DEPLOYMENT_COMPOSE_PROJECT_NAME", "agenticrag")
    timeout_seconds = int(os.environ.get("DEPLOYMENT_COMPOSE_TIMEOUT_SECONDS", "900"))
    command = [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        compose_file,
        "up",
        "-d",
        "--force-recreate",
        "--no-deps",
        *services,
    ]
    env = os.environ.copy()
    env.update(env_overrides)
    _reuse_existing_vllm_cache_bind(env, project_name, services)
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Docker Compose did not finish within {timeout_seconds} seconds.") from exc
    except OSError as exc:
        raise RuntimeError(f"Docker Compose could not be started: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(_format_process_error(completed))
    time.sleep(float(os.environ.get("DEPLOYMENT_STATUS_DELAY_SECONDS", "2")))
    return [_service_status(project_name, service) for service in services]


def _reuse_existing_vllm_cache_bind(env: dict[str, str], project_name: str, services: list[str]) -> None:
    configured = env.get(VLLM_CACHE_ENV, "")
    if configured:
        configured_source = _compose_bind_source(configured)
        if _is_compose_absolute_path(configured_source):
            env[VLLM_CACHE_ENV] = configured_source
            return
    source = _existing_mount_source(project_name, services, VLLM_CACHE_CONTAINER_PATH)
    if source:
        env[VLLM_CACHE_ENV] = _compose_bind_source(source)


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


def _existing_mount_source(project_name: str, services: list[str], destination: str) -> str | None:
    candidates = [*services, *(service for service in SERVICE_LIMITS if service not in services)]
    for service in candidates:
        container_id = _service_container_id(project_name, service)
        if not container_id:
            continue
        source = _container_mount_source(container_id, destination)
        if source:
            return source
    return None


def _service_container_id(project_name: str, service: str) -> str | None:
    command = [
        "docker",
        "ps",
        "-a",
        "--filter",
        f"label=com.docker.compose.project={project_name}",
        "--filter",
        f"label=com.docker.compose.service={service}",
        "--format",
        "{{.ID}}",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else None


def _container_mount_source(container_id: str, destination: str) -> str | None:
    command = ["docker", "inspect", container_id, "--format", "{{json .Mounts}}"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except OSError:
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        mounts = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(mounts, list):
        return None
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        if mount.get("Type") == "bind" and mount.get("Destination") == destination:
            source = mount.get("Source")
            if isinstance(source, str) and source.strip():
                return source.strip()
    return None


def _service_status(project_name: str, service: str) -> dict[str, str]:
    command = [
        "docker",
        "ps",
        "--filter",
        f"label=com.docker.compose.project={project_name}",
        "--filter",
        f"label=com.docker.compose.service={service}",
        "--format",
        "{{.Names}}\t{{.Status}}",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except OSError as exc:
        return {"service": service, "status": "unknown", "detail": f"Docker status check could not be started: {exc}"}
    if completed.returncode != 0:
        return {"service": service, "status": "unknown", "detail": _truncate(completed.stderr)}
    line = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
    if not line:
        return {"service": service, "status": "not_found", "detail": "No running container found."}
    parts = line.split("\t", 1)
    return {"service": service, "status": "running", "detail": parts[1] if len(parts) > 1 else parts[0]}


def _service_message(services: list[str]) -> str:
    if len(services) == 1:
        return services[0]
    if len(services) == 2:
        return f"{services[0]} and {services[1]}"
    return ", ".join(services[:-1]) + f", and {services[-1]}"


def _format_process_error(completed: subprocess.CompletedProcess[str]) -> str:
    stderr = _truncate(completed.stderr.strip())
    stdout = _truncate(completed.stdout.strip())
    if stderr and stdout:
        return f"Docker Compose failed: {stderr} | {stdout}"
    return f"Docker Compose failed: {stderr or stdout or f'exit code {completed.returncode}'}"


def _truncate(value: str, limit: int = 1200) -> str:
    return value if len(value) <= limit else f"{value[:limit]}..."


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DeploymentControllerHandler)
    print(f"deployment-controller listening on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
