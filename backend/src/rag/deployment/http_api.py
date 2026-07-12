"""HTTP transport for the privileged deployment-controller process."""

from __future__ import annotations

import hmac
import json
from collections.abc import Collection, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from .models import DeploymentRequest, DeploymentResult, RuntimeReadiness
from .service import DeploymentBusyError
from .validation import validate_deployment_request

MAX_REQUEST_BYTES = 64 * 1024
SERVICE_TOKEN_HEADER = "X-Service-Token"


class DeploymentApplication(Protocol):
    def apply(self, request: DeploymentRequest) -> DeploymentResult: ...

    def readiness(self) -> RuntimeReadiness: ...


class DeploymentControllerServer(ThreadingHTTPServer):
    """HTTP server carrying immutable controller process dependencies."""

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        application: DeploymentApplication,
        token: str,
        allowed_services: Collection[str],
    ) -> None:
        self.application = application
        self.token = token
        self.allowed_services = frozenset(allowed_services)
        super().__init__(server_address, DeploymentControllerHandler)


class DeploymentControllerHandler(BaseHTTPRequestHandler):
    """Map the controller HTTP contract to deployment application calls."""

    server_version = "AgenticRAGDeploymentController/1.0"
    server: DeploymentControllerServer

    def do_GET(self) -> None:
        if self.path == "/health/live":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/health/ready":
            readiness = self.server.application.readiness()
            status = HTTPStatus.OK if readiness.ready else HTTPStatus.SERVICE_UNAVAILABLE
            self._json(
                status,
                {
                    "status": "ok" if readiness.ready else "unavailable",
                    "detail": readiness.detail,
                },
            )
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
            request = validate_deployment_request(
                payload,
                allowed_services=self.server.allowed_services,
            )
            result = self.server.application.apply(request)
        except ValueError as exc:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_request", "message": str(exc)},
            )
            return
        except DeploymentBusyError as exc:
            self._json(
                HTTPStatus.CONFLICT,
                {"error": "deployment_busy", "message": str(exc)},
            )
            return
        except TimeoutError as exc:
            self._json(
                HTTPStatus.GATEWAY_TIMEOUT,
                {"error": "timeout", "message": str(exc)},
            )
            return
        except RuntimeError as exc:
            self._json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "compose_failed", "message": str(exc)},
            )
            return

        self._json(HTTPStatus.OK, _result_payload(result))

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def _authorized(self) -> bool:
        supplied = self.headers.get(SERVICE_TOKEN_HEADER, "")
        expected = self.server.token
        return bool(expected) and hmac.compare_digest(supplied.encode(), expected.encode())

    def _read_json(self) -> Mapping[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer.") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body must be JSON and no larger than 64 KiB.")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body is not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object.")
        return parsed

    def _json(self, status_code: HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _result_payload(result: DeploymentResult) -> dict[str, object]:
    return {
        "status": "applied",
        "outcome": result.outcome,
        "message": _result_message(result),
        "services": [
            {
                "service": service.service,
                "status": service.status,
                "detail": service.detail,
            }
            for service in result.services
        ],
    }


def _result_message(result: DeploymentResult) -> str:
    services = tuple(service.service for service in result.services)
    if result.outcome == "unchanged":
        verb = "uses" if len(services) == 1 else "use"
        return (
            f"{_service_message(services)} already {verb} the requested launch limits. "
            "No recreation was needed."
        )
    return (
        f"Recreated {_service_message(services)} with the requested launch limits. "
        "Model health may stay starting while weights load."
    )


def _service_message(services: tuple[str, ...]) -> str:
    if len(services) == 1:
        return services[0]
    if len(services) == 2:
        return f"{services[0]} and {services[1]}"
    return ", ".join(services[:-1]) + f", and {services[-1]}"
