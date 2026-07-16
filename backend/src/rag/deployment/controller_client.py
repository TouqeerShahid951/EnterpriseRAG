"""HTTP client for the privileged deployment controller."""

from __future__ import annotations

import json
from http.client import HTTPException as HttpClientException
from urllib import error as urlerror
from urllib import request as urlrequest

from .vllm_config_models import (
    VllmDeploymentConfigRecord,
    VllmServiceLimitsRecord,
)
from .application import (
    DeploymentControllerError,
    deployment_service_message,
)


class HttpDeploymentControllerClient:
    """Submit allowlisted vLLM deployment changes over HTTP."""

    def __init__(
        self,
        *,
        base_url: str,
        token_header: str,
        token: str,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token_header = token_header
        self._token = token
        self._timeout_seconds = timeout_seconds

    def apply(
        self,
        record: VllmDeploymentConfigRecord,
        *,
        services: list[str],
    ) -> str:
        request = urlrequest.Request(
            f"{self._base_url}/v1/vllm/apply",
            data=json.dumps(
                _deployment_controller_payload(record, services=services)
            ).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                self._token_header: self._token,
            },
        )
        try:
            with urlrequest.urlopen(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urlerror.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise DeploymentControllerError(
                f"Deployment controller returned {exc.code}: "
                f"{_truncate(error_body)}"
            ) from exc
        except urlerror.URLError as exc:
            raise DeploymentControllerError(
                f"Deployment controller is unreachable: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise DeploymentControllerError(
                "Deployment controller timed out while applying vLLM limits."
            ) from exc
        except (HttpClientException, OSError) as exc:
            raise DeploymentControllerError(
                f"Deployment controller connection failed: {exc}"
            ) from exc

        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError:
            return (
                "vLLM services were recreated; controller returned a "
                "non-JSON response."
            )
        message = parsed.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return (
            f"{deployment_service_message(services)} recreated with the saved "
            "deployment limits."
        )


def _deployment_controller_payload(
    record: VllmDeploymentConfigRecord,
    *,
    services: list[str],
) -> dict[str, object]:
    return {
        "services": services,
        "text": _service_limits_payload(record.text),
        "embeddings": _service_limits_payload(record.embeddings),
        "vision": _service_limits_payload(record.vision),
    }


def _service_limits_payload(
    record: VllmServiceLimitsRecord,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "max_model_len": record.max_model_len,
        "gpu_memory_utilization": record.gpu_memory_utilization,
        "max_num_seqs": record.max_num_seqs,
        "max_num_batched_tokens": record.max_num_batched_tokens,
    }
    if record.kv_cache_memory_bytes:
        payload["kv_cache_memory_bytes"] = record.kv_cache_memory_bytes
    return payload


def _truncate(value: str, limit: int = 1200) -> str:
    clean = value.strip()
    return clean if len(clean) <= limit else f"{clean[:limit]}..."
