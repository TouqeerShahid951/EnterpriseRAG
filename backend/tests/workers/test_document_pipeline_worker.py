"""Document-pipeline worker composition and transport adapter tests."""

from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from billiard.exceptions import SoftTimeLimitExceeded
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

tasks = import_module("apps.workers.document_pipeline.tasks")
celery_module = import_module("apps.workers.document_pipeline.celery_app")
celery_app = celery_module.celery_app
config = celery_module.config
IngestDeliveryRetry = import_module(
    "rag.ingestion.execution"
).IngestDeliveryRetry
GraphRAGDeliveryRetry = import_module(
    "rag.graphrag.task_execution"
).GraphRAGDeliveryRetry


DOCUMENT_PIPELINE_TASKS = {
    "apps.ingestion.tasks.ingest_document",
    "apps.ingestion.tasks.index_document_graphrag",
    "apps.ingestion.tasks.rebuild_graphrag_partition",
    "apps.ingestion.tasks.reextract_document_metadata",
    "apps.ingestion.tasks.reextract_document_topics",
    "apps.ingestion.tasks.reextract_document_claims",
    "apps.ingestion.tasks.reextract_document_type",
}
EXPORTED_TASKS = (
    tasks.ingest_document,
    tasks.index_document_graphrag,
    tasks.rebuild_graphrag_partition,
    tasks.reextract_document_metadata,
    tasks.reextract_document_topics,
    tasks.reextract_document_claims,
    tasks.reextract_document_type,
)


def test_document_pipeline_tasks_are_registered_only_on_their_worker_app() -> None:
    celery_app.loader.import_default_modules()

    assert DOCUMENT_PIPELINE_TASKS <= set(celery_app.tasks)
    assert "apps.workers.document_pipeline.tasks" in celery_app.conf.include
    for task in EXPORTED_TASKS:
        assert task.app is celery_app
        assert task.max_retries == 3


def test_document_pipeline_preserves_delivery_configuration() -> None:
    worker_config = celery_app.conf

    assert worker_config.task_default_queue == config.ingest_queue_name
    assert worker_config.task_serializer == "json"
    assert worker_config.accept_content == ["json"]
    assert worker_config.result_backend is None
    assert worker_config.worker_prefetch_multiplier == 1
    assert worker_config.task_acks_late is True
    assert worker_config.task_reject_on_worker_lost is True
    assert worker_config.broker_transport_options == {"visibility_timeout": 21600}
    assert worker_config.worker_concurrency == config.worker_boot_concurrency
    assert worker_config.worker_max_tasks_per_child == 1
    assert worker_config.task_soft_time_limit == celery_module.soft_time_limit
    assert worker_config.task_time_limit == celery_module.hard_time_limit

    for task_name in {
        config.graphrag_index_task_name,
        config.graphrag_partition_rebuild_task_name,
        "apps.ingestion.tasks.index_document_graphrag",
        "apps.ingestion.tasks.rebuild_graphrag_partition",
    }:
        assert worker_config.task_routes[task_name] == {
            "queue": config.graphrag_queue_name
        }


def test_document_pipeline_tasks_stay_app_local_in_multiprocessing_child() -> None:
    code = """
from celery import Celery
from apps.workers.document_pipeline.celery_app import celery_app
from apps.workers.document_pipeline import tasks

task_names = {
    tasks.ingest_document.name,
    tasks.index_document_graphrag.name,
    tasks.rebuild_graphrag_partition.name,
    tasks.reextract_document_metadata.name,
    tasks.reextract_document_topics.name,
    tasks.reextract_document_claims.name,
    tasks.reextract_document_type.name,
}
other_app = Celery("unrelated-worker", set_as_current=True)
assert task_names <= set(celery_app.tasks)
assert task_names.isdisjoint(other_app.tasks)
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


def test_configured_task_names_keep_historic_aliases() -> None:
    code = """
from apps.workers.document_pipeline.celery_app import celery_app
from apps.workers.document_pipeline import tasks

configured = {
    "custom.ingest.run",
    "custom.graphrag.index",
    "custom.graphrag.rebuild",
}
historic = {
    "apps.ingestion.tasks.ingest_document",
    "apps.ingestion.tasks.index_document_graphrag",
    "apps.ingestion.tasks.rebuild_graphrag_partition",
}
assert tasks.ingest_document.name == "custom.ingest.run"
assert tasks.index_document_graphrag.name == "custom.graphrag.index"
assert tasks.rebuild_graphrag_partition.name == "custom.graphrag.rebuild"
assert configured | historic <= set(celery_app.tasks)
for name in {
    "custom.graphrag.index",
    "custom.graphrag.rebuild",
    "apps.ingestion.tasks.index_document_graphrag",
    "apps.ingestion.tasks.rebuild_graphrag_partition",
}:
    assert celery_app.conf.task_routes[name] == {"queue": "graphrag:jobs"}
"""
    env = os.environ.copy()
    env.update(
        {
            "INGEST_TASK_NAME": "custom.ingest.run",
            "GRAPHRAG_INDEX_TASK_NAME": "custom.graphrag.index",
            "GRAPHRAG_PARTITION_REBUILD_TASK_NAME": "custom.graphrag.rebuild",
        }
    )

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"INGEST_TASK_NAME": "  "},
        {"INGEST_TASK_NAME": "celery.chain"},
        {
            "INGEST_TASK_NAME": "custom.same",
            "GRAPHRAG_INDEX_TASK_NAME": "custom.same",
        },
        {
            "GRAPHRAG_INDEX_TASK_NAME": (
                "apps.ingestion.tasks.reextract_document_topics"
            ),
        },
    ],
)
def test_document_pipeline_fails_startup_for_unsafe_task_names(
    overrides: dict[str, str],
) -> None:
    env = os.environ.copy()
    env.update(overrides)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from apps.workers.document_pipeline.celery_app import celery_app",
        ],
        check=False,
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert any(
        message in result.stderr
        for message in (
            "must not be empty",
            "reserved task namespace",
            "task name collision",
        )
    )


def test_ingestion_task_delegates_without_implicitly_queuing_graphrag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"doc_id": "doc-1", "job_id": "job-1"}
    graph_dispatches: list[object] = []
    captured: dict[str, object] = {}

    def run(value: dict[str, object], **kwargs: object) -> dict[str, object]:
        captured.update(payload=value, **kwargs)
        return {"status": "complete", **value}

    monkeypatch.setattr(tasks, "run_ingest_document", run)
    monkeypatch.setattr(
        tasks.index_document_graphrag,
        "apply_async",
        lambda *args, **kwargs: graph_dispatches.append((args, kwargs)),
    )

    result = tasks.ingest_document.run(payload)

    assert result == {"status": "complete", **payload}
    assert captured["payload"] == payload
    assert captured["timeout_error_types"] == (SoftTimeLimitExceeded,)
    assert isinstance(captured["run_token"], str)
    assert captured["run_token"]
    assert set(captured) == {"payload", "timeout_error_types", "run_token"}
    assert graph_dispatches == []


@pytest.mark.parametrize(
    ("countdown", "max_retries"),
    [(30, 12), (125, None)],
)
def test_ingestion_wrapper_translates_delivery_retry(
    monkeypatch: pytest.MonkeyPatch,
    countdown: int,
    max_retries: int | None,
) -> None:
    cause = RuntimeError("backend unavailable")
    observed_run_token: str | None = None

    class ExpectedRetry(RuntimeError):
        pass

    def run(*_args: object, **kwargs: object) -> dict[str, object]:
        nonlocal observed_run_token
        observed_run_token = str(kwargs["run_token"])
        raise IngestDeliveryRetry(
            cause,
            countdown=countdown,
            max_retries=max_retries,
        )

    def retry(**kwargs: object) -> None:
        assert kwargs == {
            "exc": cause,
            "countdown": countdown,
            "max_retries": max_retries,
            "headers": {tasks._RUN_TOKEN_HEADER: observed_run_token},
        }
        raise ExpectedRetry

    monkeypatch.setattr(tasks, "run_ingest_document", run)
    monkeypatch.setattr(tasks.ingest_document, "retry", retry)

    with pytest.raises(ExpectedRetry):
        tasks.ingest_document.run({"job_id": "job-1"})


def test_ambiguous_attempt_response_retry_reuses_only_its_run_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cause = RuntimeError("response lost after attempt commit")
    observed_tokens: list[str] = []

    class RetryScheduled(RuntimeError):
        pass

    class FakeTask:
        def __init__(self, headers: dict[str, str] | None = None) -> None:
            self.request = SimpleNamespace(id="job-1", headers=headers)
            self.retry_options: dict[str, object] | None = None

        def retry(self, **kwargs: object) -> None:
            self.retry_options = kwargs
            raise RetryScheduled

    def run(*_args: object, **kwargs: object) -> dict[str, object]:
        token = str(kwargs["run_token"])
        observed_tokens.append(token)
        if len(observed_tokens) == 1:
            raise IngestDeliveryRetry(cause, countdown=30, max_retries=12)
        return {"status": "complete"}

    monkeypatch.setattr(tasks, "run_ingest_document", run)

    first_delivery = FakeTask()
    with pytest.raises(RetryScheduled):
        tasks._run_ingest_delivery(first_delivery, {"job_id": "job-1"})

    assert first_delivery.retry_options is not None
    retry_headers = first_delivery.retry_options["headers"]
    assert isinstance(retry_headers, dict)
    assert retry_headers == {tasks._RUN_TOKEN_HEADER: observed_tokens[0]}

    retry_delivery = FakeTask(retry_headers)
    assert retry_delivery.request.id == first_delivery.request.id
    assert tasks._run_ingest_delivery(retry_delivery, {"job_id": "job-1"}) == {
        "status": "complete"
    }

    separately_published_duplicate = FakeTask()
    assert separately_published_duplicate.request.id == first_delivery.request.id
    assert tasks._run_ingest_delivery(
        separately_published_duplicate,
        {"job_id": "job-1"},
    ) == {"status": "complete"}

    assert observed_tokens[1] == observed_tokens[0]
    assert observed_tokens[2] != observed_tokens[0]


@pytest.mark.parametrize(
    "task",
    [
        tasks.reextract_document_metadata,
        tasks.reextract_document_topics,
        tasks.reextract_document_claims,
        tasks.reextract_document_type,
    ],
)
def test_reextraction_aliases_delegate_to_ingestion_execution(
    monkeypatch: pytest.MonkeyPatch,
    task: object,
) -> None:
    payload = {"job_id": "job-1"}
    calls: list[dict[str, object]] = []

    def run(value: dict[str, object], **_kwargs: object) -> dict[str, object]:
        calls.append(value)
        return {"status": "complete"}

    monkeypatch.setattr(tasks, "run_ingest_document", run)

    assert task.run(payload) == {"status": "complete"}  # type: ignore[attr-defined]
    assert calls == [payload]


def test_graphrag_index_injects_the_partition_rebuild_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"doc_id": "doc-1", "job_id": "job-1"}
    captured: dict[str, object] = {}

    def run(value: dict[str, object], **kwargs: object) -> dict[str, object]:
        captured.update(payload=value, **kwargs)
        return {"status": "complete"}

    monkeypatch.setattr(tasks, "run_document_graph_index", run)

    assert tasks.index_document_graphrag.run(payload) == {"status": "complete"}
    assert captured == {
        "payload": payload,
        "dispatch_partition_rebuild": tasks._dispatch_partition_rebuild,
    }


def test_graphrag_index_translates_retry_request_to_celery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry = GraphRAGDeliveryRetry(RuntimeError("neo4j unavailable"), countdown=17)
    monkeypatch.setattr(
        tasks,
        "run_document_graph_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(retry),
    )
    requested: dict[str, object] = {}

    def request_retry(**kwargs: object) -> RuntimeError:
        requested.update(kwargs)
        return RuntimeError("retry requested")

    monkeypatch.setattr(tasks.index_document_graphrag, "retry", request_retry)

    with pytest.raises(RuntimeError, match="retry requested"):
        tasks.index_document_graphrag.run({"doc_id": "doc-1"})

    assert requested == {"exc": retry.cause, "countdown": 17}


def test_partition_rebuild_dispatch_preserves_queue_and_countdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    payload = {"partition_key": "tenant:ops"}

    monkeypatch.setattr(
        tasks.rebuild_graphrag_partition,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )

    tasks._dispatch_partition_rebuild(payload, "graphrag:jobs", 17)

    assert calls == [
        {
            "args": [payload],
            "queue": "graphrag:jobs",
            "countdown": 17,
        }
    ]


def test_partition_rebuild_delegates_to_graphrag_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"partition_key": "tenant:ops"}

    monkeypatch.setattr(
        tasks,
        "run_partition_rebuild",
        lambda value: {"status": "complete", **value},
    )

    assert tasks.rebuild_graphrag_partition.run(payload) == {
        "status": "complete",
        **payload,
    }
