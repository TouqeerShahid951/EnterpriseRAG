"""Artifact-worker transport adapter tests."""

from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import subprocess
import sys

from billiard.exceptions import SoftTimeLimitExceeded
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

tasks = import_module("apps.workers.artifact.tasks")
celery_app = import_module("apps.workers.artifact.celery_app").celery_app
ArtifactDeliveryRetry = import_module(
    "rag.artifact_jobs.task_execution"
).ArtifactDeliveryRetry


def test_artifact_task_is_registered_on_its_worker_app() -> None:
    assert tasks.generate_artifact_job.app is celery_app
    assert tasks.generate_artifact_job.max_retries is None
    assert tasks.generate_artifact_job.name == tasks.settings.artifact_task_name
    assert "apps.workers.artifact.tasks" in celery_app.conf.include


def test_artifact_worker_preserves_delivery_configuration() -> None:
    config = celery_app.conf

    assert config.task_default_queue == tasks.settings.artifact_queue_name
    assert config.task_serializer == "json"
    assert config.accept_content == ["json"]
    assert config.result_backend is None
    assert config.worker_prefetch_multiplier == 1
    assert config.task_acks_late is True
    assert config.task_reject_on_worker_lost is True
    assert config.broker_transport_options == {"visibility_timeout": 7200}
    assert config.worker_concurrency == 1
    assert config.worker_max_tasks_per_child == 10
    assert config.task_soft_time_limit == int(
        tasks.settings.artifact_worker_timeout_seconds
    )
    assert config.task_time_limit == int(
        tasks.settings.artifact_worker_timeout_seconds + 60
    )


def test_artifact_task_stays_app_local_in_multiprocessing_child() -> None:
    code = """
from celery import Celery
from apps.workers.artifact.celery_app import celery_app
from apps.workers.artifact import tasks

task_name = tasks.generate_artifact_job.name
other_app = Celery("unrelated-worker", set_as_current=True)
assert task_name in celery_app.tasks
assert task_name not in other_app.tasks
"""
    env = os.environ.copy()
    env["FORKED_BY_MULTIPROCESSING"] = "1"

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_artifact_task_delegates_without_changing_execution_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object()
    context_validator = object()
    captured: dict[str, object] = {}

    def executor_factory() -> object:
        return object()

    def run(job_id: str, **kwargs: object) -> dict[str, object]:
        captured.update(job_id=job_id, **kwargs)
        return {"job_id": job_id, "status": "complete"}

    monkeypatch.setattr(tasks, "run_artifact_job", run)
    monkeypatch.setattr(
        tasks,
        "get_artifact_job_repository",
        lambda: repository,
    )
    monkeypatch.setattr(tasks, "get_artifact_job_executor", executor_factory)
    monkeypatch.setattr(
        tasks,
        "get_artifact_context_validator",
        lambda: context_validator,
    )

    result = tasks.generate_artifact_job.run("job-1")

    assert result == {"job_id": "job-1", "status": "complete"}
    assert captured == {
        "job_id": "job-1",
        "repository": repository,
        "executor_factory": executor_factory,
        "context_validator": context_validator,
        "timeout_error_types": (SoftTimeLimitExceeded,),
    }


def test_celery_wrapper_maps_delivery_retry_without_changing_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cause = RuntimeError("backend unavailable")

    class ExpectedRetry(RuntimeError):
        pass

    def run(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ArtifactDeliveryRetry(cause, countdown=17)

    def retry(**kwargs: object) -> None:
        assert kwargs == {"exc": cause, "countdown": 17, "max_retries": None}
        raise ExpectedRetry

    monkeypatch.setattr(tasks, "run_artifact_job", run)
    monkeypatch.setattr(tasks, "get_artifact_job_repository", object)
    monkeypatch.setattr(tasks, "get_artifact_job_executor", object)
    monkeypatch.setattr(tasks, "get_artifact_context_validator", object)
    monkeypatch.setattr(tasks.generate_artifact_job, "retry", retry)

    with pytest.raises(ExpectedRetry):
        tasks.generate_artifact_job.run("job-1")
