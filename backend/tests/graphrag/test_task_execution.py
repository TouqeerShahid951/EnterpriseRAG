from __future__ import annotations

import logging
from typing import Any

import pytest

from rag.graphrag import task_execution
from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.config import WorkerConfig


def test_graph_tasks_skip_payloads_missing_required_identifiers() -> None:
    assert task_execution.run_document_graph_index(
        {},
        dispatch_partition_rebuild=lambda *_args: None,
    ) == {"status": "skipped", "degraded_reason": "missing_doc_id"}
    assert task_execution.run_partition_rebuild({"doc_id": "doc-1"}) == {
        "status": "skipped",
        "doc_id": "doc-1",
        "degraded_reason": "missing_partition_key",
    }


def test_deduplication_failure_is_logged_and_schedules_without_marker(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = WorkerConfig.from_env()
    dispatched: list[tuple[dict[str, Any], str, int]] = []

    def marker_failure(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(task_execution, "_set_rebuild_marker", marker_failure)
    with caplog.at_level(logging.WARNING, logger="rag.graphrag.task_execution"):
        status = task_execution._enqueue_partition_rebuild(
            config,
            partition_key="/ops|clearance:1",
            doc_id="doc-1",
            job_id="job-1",
            dispatch=lambda payload, queue, countdown: dispatched.append(
                (payload, queue, countdown)
            ),
        )

    assert status == "queued"
    assert len(dispatched) == 1
    payload, queue_name, countdown = dispatched[0]
    assert "dedupe_key" not in payload
    assert queue_name == config.graphrag_queue_name
    assert countdown == config.graphrag_partition_rebuild_delay_seconds
    assert "deduplication unavailable" in caplog.text


def test_enqueue_failure_clears_marker_and_returns_degraded_status(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = WorkerConfig.from_env()
    cleared: list[str] = []
    monkeypatch.setattr(task_execution, "_set_rebuild_marker", lambda *_args: True)
    monkeypatch.setattr(
        task_execution,
        "_clear_rebuild_marker",
        lambda _config, key: cleared.append(key),
    )

    def enqueue_failure(*_args: object) -> None:
        raise RuntimeError("broker unavailable")

    with caplog.at_level(logging.ERROR, logger="rag.graphrag.task_execution"):
        status = task_execution._enqueue_partition_rebuild(
            config,
            partition_key="/ops|clearance:1",
            doc_id="doc-1",
            job_id="job-1",
            dispatch=enqueue_failure,
        )

    assert status == "enqueue_failed"
    assert cleared == [task_execution._rebuild_marker_key("/ops|clearance:1")]
    assert "partition rebuild enqueue failed" in caplog.text


def test_event_recording_failure_is_logged_without_failing_indexing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class UnavailableBackend:
        def record_event(self, **_kwargs: object) -> None:
            raise ServiceRequestError("backend", "unavailable")

    monkeypatch.setattr(
        task_execution,
        "build_backend_client",
        lambda _config: UnavailableBackend(),
    )

    with caplog.at_level(logging.WARNING, logger="rag.graphrag.task_execution"):
        task_execution._record_graphrag_event(
            WorkerConfig.from_env(),
            job_id="job-1",
            result={"status": "complete"},
        )

    assert "indexing event could not be recorded" in caplog.text


@pytest.mark.parametrize(
    "result",
    [
        {"status": "degraded", "degraded_reason": "neo4j_unavailable"},
        {"status": "complete", "partition_rebuild_status": "enqueue_failed"},
    ],
)
def test_degraded_graph_result_requests_queue_retry(result) -> None:
    with pytest.raises(task_execution.GraphRAGDeliveryRetry):
        task_execution._retry_degraded_result(result)


def test_skipped_graph_result_does_not_retry() -> None:
    result = {"status": "skipped", "degraded_reason": "no_document_chunks"}

    assert task_execution._retry_degraded_result(result) is result


def test_graph_inference_uses_shared_fastembed_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def build_inference(_runtime_config: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        task_execution,
        "build_ingestion_inference_client",
        build_inference,
    )
    config = WorkerConfig.from_env()

    task_execution._build_graph_inference(config, object())

    assert captured["dense_cache_dir"] == config.local_embeddings.dense_cache_dir
