from __future__ import annotations

from pathlib import Path

import pytest

from rag.artifact_jobs.publisher import ArtifactPublisher
from rag.repositories.artifact_jobs import InMemoryArtifactJobRepository
from rag.repositories.generated_artifact_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.services.generated_artifact_storage import LocalGeneratedArtifactStorage


def test_publisher_replaces_metadata_then_removes_the_previous_object(tmp_path) -> None:
    job = _job()
    artifacts = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    audit = _AuditRepository()
    publisher = ArtifactPublisher(
        artifact_repo_factory=lambda: artifacts,
        storage_factory=lambda: storage,
        audit_repo_factory=lambda: audit,
    )

    first = publisher.publish(
        job=job,
        filename="first.pdf",
        artifact_format="pdf",
        content_type="application/pdf",
        content=b"first",
        source_doc_ids=["doc-1"],
        smoke_warnings=[],
    )
    second = publisher.publish(
        job=job,
        filename="second.pdf",
        artifact_format="pdf",
        content_type="application/pdf",
        content=b"second",
        source_doc_ids=["doc-1"],
        smoke_warnings=[],
    )

    assert first.record.id == second.record.id
    assert first.record.object_path != second.record.object_path
    assert not Path(first.record.object_path).exists()
    assert Path(second.record.object_path).read_bytes() == b"second"
    assert second.record.expires_at == job.expires_at
    assert list(
        (tmp_path / "generated-artifacts" / "jobs" / job.id).rglob("*.pdf")
    ) == [Path(second.record.object_path)]
    assert len(audit.events) == 2


def test_publisher_compensates_first_metadata_failure(tmp_path) -> None:
    job = _job()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    publisher = ArtifactPublisher(
        artifact_repo_factory=_FailingArtifactRepository,
        storage_factory=lambda: storage,
        audit_repo_factory=_AuditRepository,
    )

    with pytest.raises(RuntimeError, match="metadata unavailable"):
        publisher.publish(
            job=job,
            filename="report.pdf",
            artifact_format="pdf",
            content_type="application/pdf",
            content=b"content",
            source_doc_ids=[],
            smoke_warnings=[],
        )

    assert not list((tmp_path / "generated-artifacts" / "jobs" / job.id).rglob("*.pdf"))


def test_publisher_preserves_previous_bytes_and_metadata_when_replacement_upsert_fails(
    tmp_path,
) -> None:
    job = _job()
    artifacts = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    successful = ArtifactPublisher(
        artifact_repo_factory=lambda: artifacts,
        storage_factory=lambda: storage,
        audit_repo_factory=_AuditRepository,
    )
    first = successful.publish(
        job=job,
        filename="first.pdf",
        artifact_format="pdf",
        content_type="application/pdf",
        content=b"first",
        source_doc_ids=[],
        smoke_warnings=[],
    )
    failing = ArtifactPublisher(
        artifact_repo_factory=lambda: _FailingReplacementRepository(artifacts),
        storage_factory=lambda: storage,
        audit_repo_factory=_AuditRepository,
    )

    with pytest.raises(RuntimeError, match="metadata unavailable"):
        failing.publish(
            job=job,
            filename="second.pdf",
            artifact_format="pdf",
            content_type="application/pdf",
            content=b"second",
            source_doc_ids=[],
            smoke_warnings=[],
        )

    current = artifacts.get_artifact(first.record.id)
    assert current == first.record
    assert Path(first.record.object_path).read_bytes() == b"first"
    assert list(
        (tmp_path / "generated-artifacts" / "jobs" / job.id).rglob("*.pdf")
    ) == [Path(first.record.object_path)]


def test_publisher_does_not_delete_a_referenced_object_after_ambiguous_commit(
    tmp_path,
) -> None:
    job = _job()
    artifacts = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    successful = ArtifactPublisher(
        artifact_repo_factory=lambda: artifacts,
        storage_factory=lambda: storage,
        audit_repo_factory=_AuditRepository,
    )
    successful.publish(
        job=job,
        filename="first.pdf",
        artifact_format="pdf",
        content_type="application/pdf",
        content=b"first",
        source_doc_ids=[],
        smoke_warnings=[],
    )
    ambiguous = ArtifactPublisher(
        artifact_repo_factory=lambda: _CommitThenFailRepository(artifacts),
        storage_factory=lambda: storage,
        audit_repo_factory=_AuditRepository,
    )

    with pytest.raises(RuntimeError, match="commit acknowledgement lost"):
        ambiguous.publish(
            job=job,
            filename="second.pdf",
            artifact_format="pdf",
            content_type="application/pdf",
            content=b"second",
            source_doc_ids=[],
            smoke_warnings=[],
        )

    current = artifacts.list_artifacts_for_job(job.id)[0]
    assert current.filename == "second.pdf"
    assert Path(current.object_path).read_bytes() == b"second"


def test_publisher_removes_uncommitted_object_when_lease_is_lost_after_storage(
    tmp_path,
) -> None:
    job = _job()
    artifacts = InMemoryGeneratedArtifactRepository()
    storage = LocalGeneratedArtifactStorage(str(tmp_path))
    guard = _FailSecondGuard()
    publisher = ArtifactPublisher(
        artifact_repo_factory=lambda: artifacts,
        storage_factory=lambda: storage,
        audit_repo_factory=_AuditRepository,
    )

    with pytest.raises(RuntimeError, match="lease lost"):
        publisher.publish(
            job=job,
            filename="report.pdf",
            artifact_format="pdf",
            content_type="application/pdf",
            content=b"content",
            source_doc_ids=[],
            smoke_warnings=[],
            expected_run_token="worker-1",
            lease_guard=guard,
        )

    assert artifacts.list_artifacts_for_job(job.id) == []
    assert not list((tmp_path / "generated-artifacts" / "jobs" / job.id).rglob("*.pdf"))


def test_publisher_reports_audit_failure_without_discarding_artifact(tmp_path) -> None:
    job = _job()
    artifacts = InMemoryGeneratedArtifactRepository()
    publisher = ArtifactPublisher(
        artifact_repo_factory=lambda: artifacts,
        storage_factory=lambda: LocalGeneratedArtifactStorage(str(tmp_path)),
        audit_repo_factory=_FailingAuditRepository,
    )

    published = publisher.publish(
        job=job,
        filename="report.pdf",
        artifact_format="pdf",
        content_type="application/pdf",
        content=b"content",
        source_doc_ids=[],
        smoke_warnings=[],
    )

    assert artifacts.get_artifact(published.record.id) is not None
    assert published.warnings == ("Artifact audit recording failed: RuntimeError",)


def _job():
    return InMemoryArtifactJobRepository().create_job(
        client_request_id="request-1",
        user_id="user-1",
        permission_version=1,
        user_email="user@example.test",
        account_type="platform_admin",
        group_paths=["/"],
        clearance_level="NATO_RESTRICTED",
        session_id="session-1",
        trace_id="trace-1",
        original_request="Create a PDF report.",
        requested_formats=["pdf"],
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=30,
    )


class _AuditRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def append_audit_event(self, **kwargs: object) -> None:
        self.events.append(dict(kwargs))


class _FailingAuditRepository:
    def append_audit_event(self, **_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")


class _FailingArtifactRepository:
    def list_artifacts_for_job(self, _job_id: str) -> list[object]:
        return []

    def create_artifact(self, **_kwargs: object):
        raise RuntimeError("metadata unavailable")

    def is_object_path_referenced(self, _object_path: str) -> bool:
        return False


class _FailingReplacementRepository:
    def __init__(self, repository: InMemoryGeneratedArtifactRepository) -> None:
        self._repository = repository

    def list_artifacts_for_job(self, job_id: str):
        return self._repository.list_artifacts_for_job(job_id)

    def create_artifact(self, **_kwargs: object):
        raise RuntimeError("metadata unavailable")

    def is_object_path_referenced(self, object_path: str) -> bool:
        return self._repository.is_object_path_referenced(object_path)


class _FailSecondGuard:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("lease lost")


class _CommitThenFailRepository:
    def __init__(self, repository: InMemoryGeneratedArtifactRepository) -> None:
        self._repository = repository

    def list_artifacts_for_job(self, job_id: str):
        return self._repository.list_artifacts_for_job(job_id)

    def create_artifact(self, **kwargs: object):
        self._repository.create_artifact(**kwargs)
        raise RuntimeError("commit acknowledgement lost")

    def is_object_path_referenced(self, object_path: str) -> bool:
        return self._repository.is_object_path_referenced(object_path)
