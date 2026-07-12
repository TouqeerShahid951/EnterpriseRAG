from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from urllib.error import HTTPError

from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.artifact_jobs.execution import (
    ArtifactJobCancelled,
    ArtifactJobExecutor,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
)
from rag.artifact_jobs import tasks
from rag.artifact_jobs.repository import InMemoryArtifactJobRepository


def test_celery_delivery_retries_are_unbounded_while_job_attempts_remain_bounded() -> (
    None
):
    assert tasks.generate_artifact_job.max_retries is None
    assert tasks.generate_artifact_job.name == tasks.settings.artifact_task_name


def test_heartbeat_recovers_after_a_transient_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovered = Event()

    class FlakyRepository:
        calls = 0

        def heartbeat(self, _job_id: str, *, run_token: str):
            _ = run_token
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("database temporarily unavailable")
            recovered.set()
            return None

    repository = FlakyRepository()
    monkeypatch.setattr(tasks, "get_artifact_job_repository", lambda: repository)
    monkeypatch.setattr(tasks, "_HEARTBEAT_FAILURE_RETRY_SECONDS", 0)

    with tasks._heartbeat("job-1", "worker-1"):
        assert recovered.wait(timeout=1)

    assert repository.calls == 2


def test_stale_job_is_reclaimed_and_old_worker_can_no_longer_mutate_it() -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)
    first, first_claimed = repo.start_attempt(job.id, run_token="worker-a")
    assert first_claimed
    assert first is not None

    old_heartbeat = datetime.now(UTC) - timedelta(minutes=5)
    repo.update_job(job.id, {"last_heartbeat_at": old_heartbeat})
    reclaimed, reclaimed_ok = repo.start_attempt(
        job.id,
        run_token="worker-b",
        stale_before=datetime.now(UTC) - timedelta(minutes=1),
    )

    assert reclaimed_ok
    assert reclaimed is not None
    assert reclaimed.run_token == "worker-b"
    assert reclaimed.attempt_count == first.attempt_count + 1
    assert repo.heartbeat(job.id, run_token="worker-a") is None
    assert (
        repo.transition_job(
            job.id,
            run_token="worker-a",
            changes={"status": "complete", "completed_at": datetime.now(UTC)},
        )
        is None
    )
    updated = repo.transition_job(
        job.id,
        run_token="worker-b",
        changes={"status": "rendering", "progress_pct": 80},
        expected_statuses={"planning"},
    )
    assert updated is not None
    assert updated.status == "rendering"


def test_repeated_stale_reclaims_stop_at_attempt_limit() -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)
    current, claimed = repo.start_attempt(job.id, run_token="worker-a")
    assert claimed
    assert current is not None

    for token in ("worker-b", "worker-c"):
        repo.update_job(
            job.id,
            {
                "last_heartbeat_at": datetime.now(UTC) - timedelta(minutes=5),
            },
        )
        current, claimed = repo.start_attempt(
            job.id,
            run_token=token,
            stale_before=datetime.now(UTC) - timedelta(minutes=1),
        )
        assert claimed
        assert current is not None

    assert current.attempt_count == current.max_attempts
    repo.update_job(
        job.id,
        {
            "last_heartbeat_at": datetime.now(UTC) - timedelta(minutes=5),
        },
    )
    exhausted, claimed = repo.start_attempt(
        job.id,
        run_token="worker-d",
        stale_before=datetime.now(UTC) - timedelta(minutes=1),
    )

    assert not claimed
    assert exhausted is not None
    assert exhausted.status == "failed"
    assert exhausted.completed_at is not None
    assert exhausted.run_token is None
    assert exhausted.error_code == "artifact_attempts_exhausted"


def test_fresh_lease_cannot_be_reclaimed_and_heartbeat_requires_owner_token() -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)
    claimed, claimed_ok = repo.start_attempt(job.id, run_token="worker-a")
    assert claimed_ok
    assert claimed is not None

    duplicate, duplicate_ok = repo.start_attempt(
        job.id,
        run_token="worker-b",
        stale_before=datetime.now(UTC) - timedelta(minutes=1),
    )

    assert not duplicate_ok
    assert duplicate == claimed
    assert repo.heartbeat(job.id, run_token="worker-b") is None
    heartbeat = repo.heartbeat(job.id, run_token="worker-a")
    assert heartbeat is not None
    assert heartbeat.run_token == "worker-a"


def test_needs_input_releases_the_worker_lease() -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)
    _, claimed = repo.start_attempt(job.id, run_token="worker-a")
    assert claimed

    waiting = repo.transition_job(
        job.id,
        run_token="worker-a",
        expected_statuses={"planning"},
        changes={"status": "needs_input", "stage": "needs_input"},
    )

    assert waiting is not None
    assert waiting.status == "needs_input"
    assert waiting.run_token is None
    assert repo.heartbeat(job.id, run_token="worker-a") is None


def test_terminal_job_is_immutable_but_explicit_user_retry_can_reset_it() -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)
    _, claimed = repo.start_attempt(job.id, run_token="worker-a")
    assert claimed
    completed = repo.transition_job(
        job.id,
        run_token="worker-a",
        changes={
            "status": "complete",
            "stage": "complete",
            "progress_pct": 100,
            "completed_at": datetime.now(UTC),
        },
    )
    assert completed is not None
    assert completed.run_token is None

    unchanged = repo.update_job(job.id, {"status": "rendering", "progress_pct": 80})
    assert unchanged is not None
    assert unchanged.status == "complete"
    assert (
        repo.transition_job(
            job.id,
            run_token="worker-a",
            changes={"status": "failed"},
        )
        is None
    )

    failed_job = _job(repo, client_request_id="retryable")
    _, claimed = repo.start_attempt(failed_job.id, run_token="worker-b")
    assert claimed
    failed = repo.transition_job(
        failed_job.id,
        run_token="worker-b",
        changes={
            "status": "failed",
            "stage": "failed",
            "progress_pct": 100,
            "completed_at": datetime.now(UTC),
        },
    )
    assert failed is not None
    retried = repo.update_job(
        failed_job.id,
        {
            "status": "queued",
            "stage": "queued",
            "progress_pct": 0,
            "cancellation_requested": False,
            "completed_at": None,
            "last_heartbeat_at": None,
        },
    )
    assert retried is not None
    assert retried.status == "queued"


def test_cancellation_cannot_be_overwritten_by_worker_completion() -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)
    _, claimed = repo.start_attempt(job.id, run_token="worker-a")
    assert claimed
    cancelled = repo.update_job(
        job.id,
        {
            "status": "cancelled",
            "stage": "cancelled",
            "progress_pct": 100,
            "cancellation_requested": True,
            "completed_at": datetime.now(UTC),
        },
    )
    assert cancelled is not None

    stale_completion = repo.transition_job(
        job.id,
        run_token="worker-a",
        changes={"status": "complete", "stage": "complete"},
    )

    assert stale_completion is None
    current = repo.get_job(job.id)
    assert current is not None
    assert current.status == "cancelled"
    assert current.cancellation_requested


@pytest.mark.parametrize(
    "lifecycle_error",
    [
        ArtifactJobCancelled("cancelled"),
        ArtifactJobLeaseLost("reclaimed"),
        ArtifactPermissionChanged("permission changed"),
        SoftTimeLimitExceeded(),
    ],
)
def test_per_format_rendering_reraises_lifecycle_errors(
    lifecycle_error: Exception,
) -> None:
    executor = object.__new__(ArtifactJobExecutor)

    def fail_check(_job_id: str) -> None:
        raise lifecycle_error

    executor._check_cancelled = fail_check  # type: ignore[method-assign]

    with pytest.raises(type(lifecycle_error)):
        executor._render_deterministic_formats(
            SimpleNamespace(id="job-1"),
            SimpleNamespace(),
            [],
            ["pdf"],
        )


@pytest.mark.parametrize("status", [401, 403, 409])
def test_internal_context_treats_authorization_statuses_as_permission_changes(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    monkeypatch.setattr(
        tasks, "urlopen", lambda *_args, **_kwargs: _raise_http_error(status)
    )

    with pytest.raises(ArtifactPermissionChanged):
        tasks._validate_internal_context("job-1")


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_internal_context_treats_backend_failures_as_transient(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    monkeypatch.setattr(
        tasks, "urlopen", lambda *_args, **_kwargs: _raise_http_error(status)
    )

    with pytest.raises(RuntimeError) as raised:
        tasks._validate_internal_context("job-1")

    assert not isinstance(raised.value, ArtifactPermissionChanged)
    assert not isinstance(raised.value, tasks.ArtifactContextRejected)


def test_context_validation_failure_is_retried_after_the_job_is_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)

    class ExpectedRetry(RuntimeError):
        pass

    def retry(**_kwargs: object) -> None:
        raise ExpectedRetry

    monkeypatch.setattr(tasks, "get_artifact_job_repository", lambda: repo)
    monkeypatch.setattr(tasks, "_heartbeat", lambda *_args: nullcontext())
    monkeypatch.setattr(
        tasks,
        "_validate_internal_context",
        lambda _job_id: (_ for _ in ()).throw(RuntimeError("backend unavailable")),
    )
    monkeypatch.setattr(tasks.generate_artifact_job, "retry", retry)

    with pytest.raises(ExpectedRetry):
        tasks.generate_artifact_job.run(job.id)

    queued = repo.get_job(job.id)
    assert queued is not None
    assert queued.status == "queued"
    assert queued.attempt_count == 1
    assert queued.run_token is None
    assert queued.errors_json[-1]["code"] == "artifact_generation_failed"
    assert (
        queued.errors_json[-1]["message"]
        == "Document generation failed. You can retry the job."
    )
    assert (
        queued.error_message_safe
        == "Document generation failed. You can retry the job."
    )


def test_authorization_failure_records_terminal_completion_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)

    monkeypatch.setattr(tasks, "get_artifact_job_repository", lambda: repo)
    monkeypatch.setattr(tasks, "_heartbeat", lambda *_args: nullcontext())
    monkeypatch.setattr(
        tasks,
        "_validate_internal_context",
        lambda _job_id: (_ for _ in ()).throw(ArtifactPermissionChanged("changed")),
    )

    with pytest.raises(ArtifactPermissionChanged):
        tasks.generate_artifact_job.run(job.id)

    failed = repo.get_job(job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.completed_at is not None
    assert failed.run_token is None


def _raise_http_error(status: int) -> None:
    raise HTTPError("http://backend.test/context", status, "error", None, None)


def _job(
    repo: InMemoryArtifactJobRepository,
    *,
    client_request_id: str = "request-1",
):
    return repo.create_job(
        client_request_id=client_request_id,
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
