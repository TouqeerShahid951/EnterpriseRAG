"""Evaluation-worker transport adapter tests."""

from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import subprocess
import sys

from billiard.exceptions import SoftTimeLimitExceeded
from celery.exceptions import Reject
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

tasks = import_module("apps.workers.evaluation.tasks")
celery_app = import_module("apps.workers.evaluation.celery_app").celery_app
EvaluationDeliveryRetry = import_module(
    "rag.evaluations.task_execution"
).EvaluationDeliveryRetry


def test_evaluation_task_is_registered_only_on_its_worker_app() -> None:
    assert tasks.run_evaluation.app is celery_app
    assert tasks.run_evaluation.max_retries is None
    assert tasks.run_evaluation.name == tasks.settings.evaluation_task_name
    assert "apps.workers.evaluation.tasks" in celery_app.conf.include


def test_evaluation_worker_preserves_delivery_configuration() -> None:
    config = celery_app.conf

    assert config.task_default_queue == tasks.settings.evaluation_queue_name
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
        tasks.settings.evaluation_worker_timeout_seconds
    )
    assert config.task_time_limit == int(
        tasks.settings.evaluation_worker_timeout_seconds + 60
    )


def test_evaluation_task_stays_app_local_in_multiprocessing_child() -> None:
    code = """
from celery import Celery
from apps.workers.evaluation.celery_app import celery_app
from apps.workers.evaluation import tasks

task_name = tasks.run_evaluation.name
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


def test_evaluation_task_uses_the_configured_compatibility_name() -> None:
    code = """
from apps.workers.evaluation.celery_app import celery_app
from apps.workers.evaluation import tasks

assert tasks.run_evaluation.name == "custom.evaluation.run"
assert "custom.evaluation.run" in celery_app.tasks
assert "rag.evaluations.tasks.run_evaluation" in celery_app.tasks
"""
    env = os.environ.copy()
    env["EVALUATION_TASK_NAME"] = "custom.evaluation.run"

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_evaluation_worker_rejects_the_reserved_celery_task_namespace() -> None:
    env = os.environ.copy()
    env["EVALUATION_TASK_NAME"] = "celery.chain"

    result = subprocess.run(
        [sys.executable, "-c", "from apps.workers.evaluation import tasks"],
        check=False,
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "reserved task namespace" in result.stderr


def test_evaluation_task_delegates_without_changing_execution_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def repository_factory() -> object:
        return object()

    def run(run_id: str, **kwargs: object) -> dict[str, object]:
        captured.update(run_id=run_id, **kwargs)
        return {"run_id": run_id, "status": "complete"}

    monkeypatch.setattr(tasks, "run_evaluation_run", run)
    monkeypatch.setattr(tasks, "get_evaluation_repository", repository_factory)

    result = tasks.run_evaluation.run("run-1")

    assert result == {"run_id": "run-1", "status": "complete"}
    assert captured == {
        "run_id": "run-1",
        "repository_factory": repository_factory,
        "executor_factory": tasks._evaluation_case_executor,
        "timeout_error_types": (SoftTimeLimitExceeded,),
    }


def test_evaluation_case_executor_propagates_worker_interrupts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = object()

    def build(**kwargs: object) -> object:
        assert kwargs == {
            "interrupt_error_types": (SoftTimeLimitExceeded,),
        }
        return executor

    monkeypatch.setattr(tasks, "default_evaluation_case_executor", build)

    assert tasks._evaluation_case_executor() is executor


def test_successful_case_schedules_fresh_same_task_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: dict[str, object] = {}

    def run(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"run_id": "run-1", "status": "running", "continue": True}

    def apply_async(**kwargs: object) -> None:
        scheduled.update(kwargs)

    monkeypatch.setattr(tasks, "run_evaluation_run", run)
    monkeypatch.setattr(tasks.run_evaluation, "apply_async", apply_async)

    result = tasks.run_evaluation.run("run-1")

    assert result == {"run_id": "run-1", "status": "running"}
    assert scheduled == {
        "args": ["run-1"],
        "queue": tasks.settings.evaluation_queue_name,
        "retry": True,
        "retry_policy": tasks._PUBLISH_RETRY_POLICY,
    }


def test_continuation_publish_failure_rejects_original_delivery_for_redelivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"run_id": "run-1", "status": "running", "continue": True}

    def apply_async(**kwargs: object) -> None:
        assert kwargs["retry"] is True
        assert kwargs["retry_policy"] == tasks._PUBLISH_RETRY_POLICY
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(tasks, "run_evaluation_run", run)
    monkeypatch.setattr(tasks.run_evaluation, "apply_async", apply_async)

    with pytest.raises(Reject) as exc_info:
        tasks.run_evaluation.run("run-1")

    assert exc_info.value.requeue is True


def test_celery_wrapper_maps_delivery_retry_without_changing_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cause = RuntimeError("backend unavailable")

    class ExpectedRetry(RuntimeError):
        pass

    def run(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise EvaluationDeliveryRetry(cause, countdown=17)

    def retry(**kwargs: object) -> None:
        assert kwargs == {
            "exc": cause,
            "countdown": 17,
            "max_retries": None,
            "retry": True,
            "retry_policy": tasks._PUBLISH_RETRY_POLICY,
        }
        raise ExpectedRetry

    monkeypatch.setattr(tasks, "run_evaluation_run", run)
    monkeypatch.setattr(tasks.run_evaluation, "retry", retry)

    with pytest.raises(ExpectedRetry):
        tasks.run_evaluation.run("run-1")


def test_retry_publish_reject_is_converted_to_requeue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cause = RuntimeError("backend unavailable")

    def run(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise EvaluationDeliveryRetry(cause, countdown=17)

    def retry(**_kwargs: object) -> None:
        raise Reject(cause, requeue=False)

    monkeypatch.setattr(tasks, "run_evaluation_run", run)
    monkeypatch.setattr(tasks.run_evaluation, "retry", retry)

    with pytest.raises(Reject) as exc_info:
        tasks.run_evaluation.run("run-1")

    assert exc_info.value.requeue is True
