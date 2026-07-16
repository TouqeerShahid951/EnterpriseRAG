"""Public API contract tests for deployment apply requests."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.deployment import routes as admin_rag_config_routes
from rag.auth.dependencies import require_platform_admin_user
from rag.auth.identity_models import UserRecord
from rag.deployment.application import VllmDeploymentApplyRejected
from rag.deployment.dependencies import get_vllm_deployment_apply_service
from rag.deployment.vllm_config_models import VllmDeploymentConfigRecord


class StubApplyService:
    def __init__(self, *, error_message: str | None = None) -> None:
        self.error_message = error_message
        self.calls: list[tuple[VllmDeploymentConfigRecord, list[str] | None]] = []

    def apply(
        self,
        desired: VllmDeploymentConfigRecord,
        *,
        requested_services: list[str] | None,
    ) -> VllmDeploymentConfigRecord:
        self.calls.append((desired, requested_services))
        if self.error_message:
            raise VllmDeploymentApplyRejected(
                replace(
                    desired,
                    apply_status="failed",
                    message=self.error_message,
                )
            )
        return replace(
            desired,
            apply_status="applied",
            message="deployment complete",
        )


def test_apply_route_preserves_response_and_request_mapping() -> None:
    service = StubApplyService()
    client, user = _client(service)

    response = client.post(
        "/admin/vllm-deployment-config/apply",
        json=_request_payload(services=["text", "vision"]),
    )

    assert response.status_code == 200
    assert response.json()["apply_status"] == "applied"
    assert response.json()["message"] == "deployment complete"
    desired, services = service.calls[0]
    assert services == ["text", "vision"]
    assert desired.updated_by == user.id
    assert desired.text.max_model_len == 4096
    assert desired.vision.kv_cache_memory_bytes == "2G"


def test_apply_route_preserves_controller_failure_status_and_detail() -> None:
    service = StubApplyService(error_message="controller unavailable")
    client, _ = _client(service)

    response = client.post(
        "/admin/vllm-deployment-config/apply",
        json=_request_payload(services=["embeddings"]),
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "code": "vllm_deployment_apply_failed",
            "message": "controller unavailable",
        }
    }


def _client(service: StubApplyService) -> tuple[TestClient, UserRecord]:
    user = UserRecord(
        id=str(uuid4()),
        email="admin@example.test",
        name="Admin",
        password_hash="hash",
        is_active=True,
        account_type="system_admin",
        clearance_level="COSMIC_TOP_SECRET",
        must_change_password=False,
        permission_version=1,
        group_paths=(),
    )
    app = FastAPI()
    app.include_router(admin_rag_config_routes.router)
    app.dependency_overrides[require_platform_admin_user] = lambda: user
    app.dependency_overrides[
        get_vllm_deployment_apply_service
    ] = lambda: service
    return TestClient(app), user


def _request_payload(*, services: list[str]) -> dict[str, object]:
    return {
        "services": services,
        "text": _limits(max_model_len=4096, kv_cache_memory_bytes="2G"),
        "embeddings": _limits(
            max_model_len=2048,
            kv_cache_memory_bytes=None,
        ),
        "vision": _limits(max_model_len=2048, kv_cache_memory_bytes="2G"),
    }


def _limits(
    *,
    max_model_len: int,
    kv_cache_memory_bytes: str | None,
) -> dict[str, object]:
    return {
        "max_model_len": max_model_len,
        "gpu_memory_utilization": 0.1,
        "kv_cache_memory_bytes": kv_cache_memory_bytes,
        "max_num_seqs": 1,
        "max_num_batched_tokens": max_model_len,
    }
