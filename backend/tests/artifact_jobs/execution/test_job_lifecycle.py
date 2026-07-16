from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from urllib.error import HTTPError

from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.artifact_jobs.adapters import internal_context_http
from rag.artifact_jobs.adapters.internal_context_http import (
    HttpArtifactContextValidator,
)
from rag.artifact_jobs.execution import (
    ArtifactJobCancelled,
    ArtifactJobExecutor,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
)
from rag.artifact_jobs import task_execution
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.task_execution import (
    ArtifactContextRejected,
    ArtifactDeliveryRetry,
    run_artifact_job,
)


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
    monkeypatch.setattr(task_execution, "_HEARTBEAT_FAILURE_RETRY_SECONDS", 0)

    with task_execution._heartbeat(repository, "job-1", "worker-1"):
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
        internal_context_http,
        "urlopen",
        lambda *_args, **_kwargs: _raise_http_error(status),
    )

    with pytest.raises(ArtifactPermissionChanged):
        _context_validator().validate("job-1")


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_internal_context_treats_backend_failures_as_transient(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    monkeypatch.setattr(
        internal_context_http,
        "urlopen",
        lambda *_args, **_kwargs: _raise_http_error(status),
    )

    with pytest.raises(RuntimeError) as raised:
        _context_validator().validate("job-1")

    assert not isinstance(raised.value, ArtifactPermissionChanged)
    assert not isinstance(raised.value, ArtifactContextRejected)


def test_internal_context_uses_the_server_service_token_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: dict[str, str] = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def open_request(request, *, timeout: float):
        assert timeout == 5
        captured_headers.update(
            {name.lower(): value for name, value in request.header_items()}
        )
        return Response()

    monkeypatch.setattr(internal_context_http, "urlopen", open_request)

    _context_validator().validate("job-1")

    assert captured_headers["x-service-token"] == "service-token"


def test_context_validation_failure_is_retried_after_the_job_is_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)

    monkeypatch.setattr(task_execution, "_heartbeat", lambda *_args: nullcontext())

    with pytest.raises(ArtifactDeliveryRetry) as raised:
        run_artifact_job(
            job.id,
            repository=repo,
            executor_factory=_UnexpectedExecutor,
            context_validator=_FailingContextValidator(
                RuntimeError("backend unavailable")
            ),
        )

    assert raised.value.countdown == 30
    assert isinstance(raised.value.cause, RuntimeError)

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


def test_soft_timeout_preserves_timeout_retry_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)
    monkeypatch.setattr(task_execution, "_heartbeat", lambda *_args: nullcontext())

    with pytest.raises(ArtifactDeliveryRetry) as raised:
        run_artifact_job(
            job.id,
            repository=repo,
            executor_factory=lambda: _FailingExecutor(SoftTimeLimitExceeded()),
            context_validator=_PassingContextValidator(),
            timeout_error_types=(SoftTimeLimitExceeded,),
        )

    assert raised.value.countdown == 30
    assert isinstance(raised.value.cause, SoftTimeLimitExceeded)
    queued = repo.get_job(job.id)
    assert queued is not None
    assert queued.status == "queued"
    assert queued.error_code == "artifact_timeout"
    assert (
        queued.error_message_safe
        == "Document generation timed out. You can retry the job."
    )


def test_context_rejection_records_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)
    monkeypatch.setattr(task_execution, "_heartbeat", lambda *_args: nullcontext())

    result = run_artifact_job(
        job.id,
        repository=repo,
        executor_factory=_UnexpectedExecutor,
        context_validator=_FailingContextValidator(
            ArtifactContextRejected("invalid context")
        ),
    )

    assert result == {"job_id": job.id, "status": "failed"}
    failed = repo.get_job(job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "artifact_context_rejected"
    assert failed.completed_at is not None


def test_authorization_failure_records_terminal_completion_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryArtifactJobRepository()
    job = _job(repo)

    monkeypatch.setattr(task_execution, "_heartbeat", lambda *_args: nullcontext())

    with pytest.raises(ArtifactPermissionChanged):
        run_artifact_job(
            job.id,
            repository=repo,
            executor_factory=_UnexpectedExecutor,
            context_validator=_FailingContextValidator(
                ArtifactPermissionChanged("changed")
            ),
        )

    failed = repo.get_job(job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.completed_at is not None
    assert failed.run_token is None


def _raise_http_error(status: int) -> None:
    raise HTTPError("http://backend.test/context", status, "error", None, None)


def _context_validator() -> HttpArtifactContextValidator:
    return HttpArtifactContextValidator(
        base_url="http://backend.test",
        service_token="service-token",
        timeout_seconds=5,
    )


class _FailingContextValidator:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def validate(self, _job_id: str) -> None:
        raise self.error


class _UnexpectedExecutor:
    def execute(self, _job_id: str, *, run_token: str | None = None) -> None:
        _ = run_token
        raise AssertionError("executor must not run when context validation fails")


class _FailingExecutor:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def execute(self, _job_id: str, *, run_token: str | None = None) -> None:
        _ = run_token
        raise self.error


class _PassingContextValidator:
    def validate(self, _job_id: str) -> None:
        return None


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
