from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from rag.api.routes.query_routes import get_generated_artifact_content
from rag.artifact_jobs.adapters.generated_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.artifact_jobs.repository import InMemoryArtifactJobRepository


def test_expired_artifact_download_is_rejected_before_storage_read() -> None:
    repository = InMemoryGeneratedArtifactRepository()
    artifact = repository.create_artifact(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename="report.pdf",
        format="pdf",
        content_type="application/pdf",
        object_path="generated-artifacts/report.pdf",
        size_bytes=10,
        source_doc_ids=[],
        prompt="Create a report.",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    storage = _UnreadStorage()

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            get_generated_artifact_content(
                artifact.id,
                user=SimpleNamespace(id="user-1", permission_version=1),
                artifact_repo=repository,
                artifact_storage=storage,
                audit_repo=SimpleNamespace(),
            )
        )

    assert raised.value.status_code == 404
    assert storage.read_called is False


def test_audit_failure_does_not_block_a_valid_artifact_download() -> None:
    repository = InMemoryGeneratedArtifactRepository()
    artifact = repository.create_artifact(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename="report.pdf",
        format="pdf",
        content_type="application/pdf",
        object_path="generated-artifacts/report.pdf",
        size_bytes=10,
        source_doc_ids=[],
        prompt="Create a report.",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    response = asyncio.run(
        get_generated_artifact_content(
            artifact.id,
            user=SimpleNamespace(id="user-1", permission_version=1),
            artifact_repo=repository,
            artifact_storage=_ReadableStorage(),
            audit_repo=_FailingAuditRepository(),
        )
    )

    assert response.media_type == "application/pdf"
    assert response.headers["content-length"] == "7"


def test_job_artifact_is_not_downloadable_until_the_parent_job_finishes() -> None:
    jobs = InMemoryArtifactJobRepository()
    job = jobs.create_job(
        client_request_id="request-1",
        user_id="user-1",
        permission_version=1,
        user_email="user@example.test",
        account_type="platform_admin",
        group_paths=["/"],
        clearance_level="NATO_RESTRICTED",
        session_id="session-1",
        trace_id="trace-1",
        original_request="Create a report.",
        requested_formats=["pdf"],
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=1,
    )
    repository = InMemoryGeneratedArtifactRepository()
    artifact = repository.create_artifact(
        job_id=job.id,
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename="report.pdf",
        format="pdf",
        content_type="application/pdf",
        object_path="generated-artifacts/report.pdf",
        size_bytes=7,
        source_doc_ids=[],
        prompt="Create a report.",
        expires_at=job.expires_at,
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            get_generated_artifact_content(
                artifact.id,
                user=SimpleNamespace(id="user-1", permission_version=1),
                artifact_repo=repository,
                artifact_job_repo=jobs,
                artifact_storage=_ReadableStorage(),
                audit_repo=_AuditRepository(),
            )
        )
    assert raised.value.status_code == 404

    jobs.update_job(
        job.id,
        {
            "status": "complete",
            "stage": "complete",
            "progress_pct": 100,
            "completed_at": datetime.now(UTC),
        },
    )
    response = asyncio.run(
        get_generated_artifact_content(
            artifact.id,
            user=SimpleNamespace(id="user-1", permission_version=1),
            artifact_repo=repository,
            artifact_job_repo=jobs,
            artifact_storage=_ReadableStorage(),
            audit_repo=_AuditRepository(),
        )
    )
    assert response.headers["content-length"] == "7"


def test_artifact_download_rechecks_current_access_to_every_source_document() -> None:
    repository = InMemoryGeneratedArtifactRepository()
    artifact = repository.create_artifact(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename="report.pdf",
        format="pdf",
        content_type="application/pdf",
        object_path="generated-artifacts/report.pdf",
        size_bytes=7,
        source_doc_ids=["doc-1"],
        prompt="Create a report.",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    storage = _UnreadStorage()
    user = SimpleNamespace(
        id="user-1",
        permission_version=1,
        account_type="platform_admin",
        clearance_level="NATO_RESTRICTED",
        group_paths=("/",),
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            get_generated_artifact_content(
                artifact.id,
                user=user,
                artifact_repo=repository,
                artifact_storage=storage,
                audit_repo=_RevokedDocumentAuditRepository(),
            )
        )

    assert raised.value.status_code == 404
    assert storage.read_called is False


class _UnreadStorage:
    def __init__(self) -> None:
        self.read_called = False

    def read(self, _object_path: str):
        self.read_called = True
        raise AssertionError("expired artifacts must be rejected before storage reads")


class _ReadableStorage:
    def read(self, _object_path: str):
        return SimpleNamespace(
            content=b"content",
            content_type="application/pdf",
            filename="report.pdf",
        )


class _FailingAuditRepository:
    def append_audit_event(self, **_kwargs: object) -> None:
        raise RuntimeError("audit database unavailable")


class _AuditRepository:
    def append_audit_event(self, **_kwargs: object) -> None:
        return None


class _RevokedDocumentAuditRepository:
    def get_document(self, _document_id: str):
        return SimpleNamespace(
            clearance_level="NATO_SECRET",
            access_group_paths=("/",),
        )
