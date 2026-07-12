from __future__ import annotations

import pytest

from rag.deployment.validation import validate_deployment_request


def test_validation_normalizes_selected_service_limits_to_managed_environment() -> None:
    request = validate_deployment_request(
        {
            "services": ["vllm-text"],
            "text": _limits(kv_cache_memory_bytes="3GiB"),
        }
    )

    assert request.services == ("vllm-text",)
    assert request.environment == {
        "VLLM_TEXT_MAX_MODEL_LEN": "4096",
        "VLLM_TEXT_GPU_MEMORY_UTILIZATION": "0.25",
        "VLLM_TEXT_KV_CACHE_MEMORY_BYTES": "3GiB",
        "VLLM_TEXT_MAX_NUM_SEQS": "2",
        "VLLM_TEXT_MAX_NUM_BATCHED_TOKENS": "4096",
    }


def test_validation_uses_all_services_when_services_are_omitted() -> None:
    request = validate_deployment_request(
        {
            "text": _limits(kv_cache_memory_bytes="2G"),
            "embeddings": _limits(),
            "vision": _limits(kv_cache_memory_bytes="1G"),
        }
    )

    assert request.services == ("vllm-text", "vllm-embeddings", "vllm-vision")
    assert dict(request.deployments[1].environment) == {
        "VLLM_EMBED_MAX_MODEL_LEN": "4096",
        "VLLM_EMBED_GPU_MEMORY_UTILIZATION": "0.25",
        "VLLM_EMBED_MAX_NUM_SEQS": "2",
        "VLLM_EMBED_MAX_NUM_BATCHED_TOKENS": "4096",
    }
    assert dict(request.deployments[2].environment) == {
        "VLLM_VISION_MAX_MODEL_LEN": "4096",
        "VLLM_VISION_GPU_MEMORY_UTILIZATION": "0.25",
        "VLLM_VISION_KV_CACHE_MEMORY_BYTES": "1G",
        "VLLM_VISION_MAX_NUM_SEQS": "2",
        "VLLM_VISION_MAX_NUM_BATCHED_TOKENS": "4096",
    }


def test_validation_rejects_service_outside_configured_allowlist() -> None:
    with pytest.raises(ValueError, match="not allowlisted: vllm-vision"):
        validate_deployment_request(
            {"services": ["vllm-vision"], "vision": _limits()},
            allowed_services={"vllm-text"},
        )


def test_validation_requires_limits_for_each_selected_service() -> None:
    with pytest.raises(ValueError, match="embeddings limits are required"):
        validate_deployment_request({"services": ["vllm-embeddings"]})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("max_model_len", 255, "must be between 256 and 262144"),
        ("gpu_memory_utilization", 0, "must be greater than 0.0"),
        ("gpu_memory_utilization", "nan", "must be greater than 0.0"),
        ("max_num_seqs", True, "must be an integer"),
        ("max_num_batched_tokens", 262145, "must be between 256 and 262144"),
        ("kv_cache_memory_bytes", "0GiB", "not a valid byte-size value"),
    ],
)
def test_validation_rejects_invalid_launch_limits(field: str, value: object, message: str) -> None:
    limits = _limits(kv_cache_memory_bytes="2G")
    limits[field] = value

    with pytest.raises(ValueError, match=message):
        validate_deployment_request({"services": ["vllm-text"], "text": limits})


def _limits(*, kv_cache_memory_bytes: str | None = None) -> dict[str, object]:
    limits: dict[str, object] = {
        "max_model_len": 4096,
        "gpu_memory_utilization": 0.25,
        "max_num_seqs": 2,
        "max_num_batched_tokens": 4096,
    }
    if kv_cache_memory_bytes is not None:
        limits["kv_cache_memory_bytes"] = kv_cache_memory_bytes
    return limits
