"""Boundary validation and normalization for deployment requests."""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Mapping
from typing import Any

from .models import DeploymentRequest, ServiceDeployment

DEFAULT_SERVICES = ("vllm-text", "vllm-embeddings", "vllm-vision")
SERVICE_LIMITS: dict[str, tuple[str, dict[str, str]]] = {
    "vllm-text": (
        "text",
        {
            "max_model_len": "VLLM_TEXT_MAX_MODEL_LEN",
            "gpu_memory_utilization": "VLLM_TEXT_GPU_MEMORY_UTILIZATION",
            "kv_cache_memory_bytes": "VLLM_TEXT_KV_CACHE_MEMORY_BYTES",
            "max_num_seqs": "VLLM_TEXT_MAX_NUM_SEQS",
            "max_num_batched_tokens": "VLLM_TEXT_MAX_NUM_BATCHED_TOKENS",
        },
    ),
    "vllm-embeddings": (
        "embeddings",
        {
            "max_model_len": "VLLM_EMBED_MAX_MODEL_LEN",
            "gpu_memory_utilization": "VLLM_EMBED_GPU_MEMORY_UTILIZATION",
            "max_num_seqs": "VLLM_EMBED_MAX_NUM_SEQS",
            "max_num_batched_tokens": "VLLM_EMBED_MAX_NUM_BATCHED_TOKENS",
        },
    ),
    "vllm-vision": (
        "vision",
        {
            "max_model_len": "VLLM_VISION_MAX_MODEL_LEN",
            "gpu_memory_utilization": "VLLM_VISION_GPU_MEMORY_UTILIZATION",
            "kv_cache_memory_bytes": "VLLM_VISION_KV_CACHE_MEMORY_BYTES",
            "max_num_seqs": "VLLM_VISION_MAX_NUM_SEQS",
            "max_num_batched_tokens": "VLLM_VISION_MAX_NUM_BATCHED_TOKENS",
        },
    ),
}
KV_CACHE_PATTERN = re.compile(r"^[1-9][0-9]*(B|K|M|G|T|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?$")


def validate_deployment_request(
    payload: Mapping[str, Any],
    *,
    allowed_services: Collection[str] = DEFAULT_SERVICES,
) -> DeploymentRequest:
    """Validate an untrusted request payload and return an immutable command."""

    raw_services = payload.get("services") or DEFAULT_SERVICES
    if not isinstance(raw_services, list | tuple) or not raw_services:
        raise ValueError("services must be a non-empty list.")

    services = tuple(str(service) for service in raw_services)
    allowed = frozenset(allowed_services)
    blocked = [service for service in services if service not in allowed or service not in SERVICE_LIMITS]
    if blocked:
        raise ValueError(f"Requested services are not allowlisted: {', '.join(blocked)}")

    deployments: list[ServiceDeployment] = []
    for service in services:
        payload_key, environment_names = SERVICE_LIMITS[service]
        raw_limits = payload.get(payload_key)
        if not isinstance(raw_limits, Mapping):
            raise ValueError(f"{payload_key} limits are required.")
        limits = _validate_limits(payload_key, raw_limits)
        environment = tuple(
            (environment_name, str(limits[field]))
            for field, environment_name in environment_names.items()
            if field in limits
        )
        deployments.append(ServiceDeployment(service=service, environment=environment))
    return DeploymentRequest(deployments=tuple(deployments))


def _validate_limits(key: str, limits: Mapping[str, Any]) -> dict[str, int | float | str]:
    normalized: dict[str, int | float | str] = {
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
        if not KV_CACHE_PATTERN.fullmatch(value):
            raise ValueError(f"{key}.kv_cache_memory_bytes is not a valid byte-size value.")
        normalized["kv_cache_memory_bytes"] = value
    return normalized


def _int_range(value: Any, minimum: int, maximum: int, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    return parsed


def _float_range(
    value: Any,
    minimum: float,
    maximum: float,
    field: str,
    *,
    exclusive_min: bool = False,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number.") from exc
    if not math.isfinite(parsed) or (parsed <= minimum if exclusive_min else parsed < minimum) or parsed > maximum:
        lower = f"greater than {minimum}" if exclusive_min else f"at least {minimum}"
        raise ValueError(f"{field} must be {lower} and no more than {maximum}.")
    return parsed

