from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rag.artifact_jobs.adapters.generated_memory import InMemoryGeneratedArtifactRepository

from generated_artifact_lifecycle_support import (
    CapturingGuardedPostgresRepository,
    CapturingPostgresRepository,
    create_artifact,
)


def test_in_memory_repository_duplicate_job_format_matches_postgres_upsert() -> None:
    repository = InMemoryGeneratedArtifactRepository(default_retention_days=7)
    initial_expiry = datetime(2026, 1, 2, tzinfo=UTC)
    first = create_artifact(
        repository,
        job_id="job-1",
        object_path="generated-artifacts/first.docx",
        expires_at=initial_expiry,
        filename="first.docx",
        size_bytes=10,
    )

    second = create_artifact(
        repository,
        job_id="job-1",
        object_path="generated-artifacts/second.docx",
        expires_at=None,
        filename="second.docx",
        size_bytes=20,
    )

    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.expires_at == initial_expiry
    assert second.filename == "second.docx"
    assert second.object_path == "generated-artifacts/second.docx"
    assert second.size_bytes == 20
    assert repository.list_artifacts_for_job("job-1") == [second]


def test_in_memory_repository_legacy_trace_format_is_idempotent() -> None:
    repository = InMemoryGeneratedArtifactRepository()
    first = create_artifact(
        repository,
        job_id=None,
        object_path="generated-artifacts/query/first.pdf",
        expires_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    second = create_artifact(
        repository,
        job_id=None,
        object_path="generated-artifacts/query/second.pdf",
        expires_at=datetime(2026, 1, 3, tzinfo=UTC),
        filename="second.pdf",
    )

    assert second.id == first.id
    assert second.filename == "second.pdf"
    assert second.object_path == "generated-artifacts/query/second.pdf"


def test_in_memory_repository_lists_and_conditionally_deletes_expired_artifacts() -> (
    None
):
    repository = InMemoryGeneratedArtifactRepository()
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    expired = create_artifact(
        repository,
        job_id="expired-job",
        object_path="generated-artifacts/expired.pdf",
        expires_at=cutoff - timedelta(seconds=1),
    )
    create_artifact(
        repository,
        job_id="future-job",
        object_path="generated-artifacts/future.pdf",
        expires_at=cutoff + timedelta(seconds=1),
    )

    assert repository.list_expired_artifacts(expires_before=cutoff) == [expired]
    assert not repository.delete_expired_artifact(
        expired.id,
        expires_before=cutoff,
        expected_object_path="generated-artifacts/wrong.pdf",
    )
    assert repository.delete_expired_artifact(
        expired.id,
        expires_before=cutoff,
        expected_object_path=expired.object_path,
    )
    assert repository.get_artifact(expired.id) is None


def test_postgres_upsert_carries_expiry_and_configured_default_retention() -> None:
    repository = CapturingPostgresRepository(default_retention_days=12)
    expires_at = datetime(2026, 2, 1, tzinfo=UTC)

    record = repository.create_artifact(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename="artifact.pdf",
        format="pdf",
        content_type="application/pdf",
        object_path="generated-artifacts/artifact.pdf",
        size_bytes=8,
        source_doc_ids=["doc-1"],
        prompt="Generate a report.",
        job_id="job-1",
        expires_at=expires_at,
    )

    assert "expires_at = EXCLUDED.expires_at" in repository.query
    assert repository.params[-3:] == (expires_at, "job-1", 12)
    assert repository.query.count("%s") == len(repository.params)
    assert record.expires_at == expires_at


def test_postgres_guarded_upsert_locks_and_validates_the_worker_lease() -> None:
    repository = CapturingGuardedPostgresRepository(default_retention_days=12)

    with pytest.raises(RuntimeError, match="publication lease"):
        repository.create_artifact(
            user_id="user-1",
            permission_version=1,
            session_id="session-1",
            trace_id="trace-1",
            requested_formats=["pdf"],
            filename="artifact.pdf",
            format="pdf",
            content_type="application/pdf",
            object_path="generated-artifacts/artifact.pdf",
            size_bytes=8,
            source_doc_ids=["doc-1"],
            prompt="Generate a report.",
            job_id="job-1",
            expires_at=datetime(2026, 2, 1, tzinfo=UTC),
            expected_job_run_token="worker-token",
        )

    assert "WITH authorized_job AS" in repository.query
    assert "FOR UPDATE" in repository.query
    assert repository.params[:2] == ("job-1", "worker-token")
    assert repository.query.count("%s") == len(repository.params)


def test_postgres_legacy_upsert_uses_trace_format_idempotency_key() -> None:
    repository = CapturingPostgresRepository(default_retention_days=12)

    repository.create_artifact(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        trace_id="trace-1",
        requested_formats=["pdf"],
        filename="artifact.pdf",
        format="pdf",
        content_type="application/pdf",
        object_path="generated-artifacts/query/artifact.pdf",
        size_bytes=8,
        source_doc_ids=[],
        prompt="Generate a report.",
        job_id=None,
        expires_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert (
        "ON CONFLICT (user_id, permission_version, trace_id, artifact_format) "
        "WHERE job_id IS NULL" in repository.query
    )
