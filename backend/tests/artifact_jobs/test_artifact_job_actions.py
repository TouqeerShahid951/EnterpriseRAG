from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rag.artifact_jobs.adapters.generated_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.artifact_jobs.contracts import DocumentPlan
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.service import ArtifactJobActionError, ArtifactJobService
from rag.auth.context import UserContext
from rag.query.schemas import QueryRequest


class _Queue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


def test_duplicate_queued_submission_is_redispatched() -> None:
    jobs = InMemoryArtifactJobRepository()
    queue = _Queue()
    service = _service(jobs, queue)
    request = QueryRequest(
        query="Create a PDF report about quarterly risk",
        client_request_id="request-1",
    )

    first = service.submit(
        request=request,
        user=_user(),
        trace_id="trace-1",
        session_id="session-1",
        formats=("pdf",),
        conversation_context=[],
    )
    second = service.submit(
        request=request,
        user=_user(),
        trace_id="trace-2",
        session_id="session-1",
        formats=("pdf",),
        conversation_context=[],
    )

    assert first.id == second.id
    assert queue.job_ids == [first.id, first.id]


def test_clarification_answers_must_match_requested_questions() -> None:
    jobs = InMemoryArtifactJobRepository()
    queue = _Queue()
    service = _service(jobs, queue)
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
        original_request="Create a PDF",
        requested_formats=["pdf"],
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=1,
    )
    question = "What topic should this artifact cover?"
    jobs.update_job(
        job.id,
        {
            "status": "needs_input",
            "stage": "needs_input",
            "plan_json": DocumentPlan(
                title="Clarification Needed",
                purpose="Clarify the artifact topic.",
                clarification_questions=[question],
            ).model_dump(mode="json"),
        },
    )

    with pytest.raises(ArtifactJobActionError) as raised:
        service.add_clarifications(
            job.id, _user(), {"Unrequested question": "Quarterly risk"}
        )

    assert raised.value.code == "artifact_clarification_invalid"
    assert queue.job_ids == []


def test_clarification_resume_does_not_consume_retry_budget() -> None:
    jobs = InMemoryArtifactJobRepository()
    queue = _Queue()
    service = _service(jobs, queue)
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
        original_request="Create a PDF",
        requested_formats=["pdf"],
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=1,
    )
    running, claimed = jobs.start_attempt(job.id, run_token="worker-1")
    assert claimed and running is not None
    question = "What topic should this artifact cover?"
    waiting = jobs.transition_job(
        job.id,
        run_token="worker-1",
        changes={
            "status": "needs_input",
            "stage": "needs_input",
            "plan_json": DocumentPlan(
                title="Clarification Needed",
                purpose="Clarify the artifact topic.",
                clarification_questions=[question],
            ).model_dump(mode="json"),
        },
    )
    assert waiting is not None and waiting.attempt_count == 1

    summary = service.add_clarifications(job.id, _user(), {question: "Quarterly risk"})

    assert summary.status == "queued"
    assert summary.attempt_count == 0
    resumed, resumed_claimed = jobs.start_attempt(job.id, run_token="worker-2")
    assert resumed_claimed and resumed is not None
    assert resumed.attempt_count == 1


def test_job_detail_redacts_internal_worker_error_messages() -> None:
    jobs = InMemoryArtifactJobRepository()
    queue = _Queue()
    service = _service(jobs, queue)
    job = _create_job(jobs, retention_days=1)
    jobs.update_job(
        job.id,
        {
            "errors_json": [
                {
                    "stage": "rendering",
                    "code": "artifact_format_failed",
                    "message": "RuntimeError: secret filesystem path /srv/private/report.pdf",
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
            ]
        },
    )

    detail = service.get_for_user(job.id, _user())

    assert detail.errors[0]["code"] == "artifact_format_failed"
    assert "secret filesystem path" not in str(detail.errors)
    assert (
        detail.errors[0]["message"]
        == "One requested output format could not be generated."
    )


def test_expired_job_is_not_returned_to_the_user() -> None:
    jobs = InMemoryArtifactJobRepository()
    service = _service(jobs, _Queue())
    job = _create_job(jobs, retention_days=0)

    with pytest.raises(ArtifactJobActionError) as raised:
        service.get_for_user(job.id, _user())

    assert raised.value.code == "artifact_job_not_found"


def test_expired_idempotency_record_is_not_redispatched_or_returned() -> None:
    jobs = InMemoryArtifactJobRepository()
    queue = _Queue()
    service = _service(jobs, queue)
    _create_job(jobs, retention_days=0)

    with pytest.raises(ArtifactJobActionError) as raised:
        service.submit(
            request=QueryRequest(
                query="Create a PDF report.",
                client_request_id="request-helper",
            ),
            user=_user(),
            trace_id="trace-new",
            session_id="session-1",
            formats=("pdf",),
            conversation_context=[],
        )

    assert raised.value.code == "artifact_job_expired"
    assert queue.job_ids == []


def _create_job(
    jobs: InMemoryArtifactJobRepository,
    *,
    retention_days: int,
):
    return jobs.create_job(
        client_request_id="request-helper",
        user_id="user-1",
        permission_version=1,
        user_email="user@example.test",
        account_type="platform_admin",
        group_paths=["/"],
        clearance_level="NATO_RESTRICTED",
        session_id="session-1",
        trace_id="trace-helper",
        original_request="Create a PDF",
        requested_formats=["pdf"],
        group_path=None,
        document_ids=[],
        conversation_context=[],
        retention_days=retention_days,
    )


def _service(jobs: InMemoryArtifactJobRepository, queue: _Queue) -> ArtifactJobService:
    artifacts = InMemoryGeneratedArtifactRepository()
    return ArtifactJobService(
        repo_factory=lambda: jobs,
        artifact_repo_factory=lambda: artifacts,
        queue_factory=lambda: queue,
        retention_days=30,
    )


def _user() -> UserContext:
    return UserContext(
        user_id="user-1",
        email="user@example.test",
        account_type="platform_admin",
        group_paths=("/",),
        permission_version=1,
    )
