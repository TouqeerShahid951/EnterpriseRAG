from __future__ import annotations

import base64
from datetime import UTC, datetime
import json

from rag.graphrag.adapters.redis_queue_monitor import RedisGraphRAGQueueMonitor
from rag.graphrag.monitoring import inspect_graphrag_status
from rag.ingestion.worker_control import WorkerActiveTask, WorkerCapacity, WorkerControlResult


def test_monitoring_preserves_worker_and_queue_degraded_diagnostics() -> None:
    status = inspect_graphrag_status(
        enabled=True,
        queue_name="graphrag:jobs",
        control=_FailingControl(),  # type: ignore[arg-type]
        queue_monitor=_FailingQueueMonitor(),
    )

    assert status.enabled is True
    assert status.queued_jobs is None
    assert status.queue_error == "ConnectionError: redis unavailable"
    assert status.queued_tasks == ()
    assert status.worker_online is False
    assert status.worker_error == "TimeoutError: celery inspect timed out"


def test_monitoring_maps_active_worker_timing_and_queued_celery_messages() -> None:
    started_at = datetime(2026, 7, 13, 10, 0, tzinfo=UTC)
    raw_message = _celery_message(
        task_id="queued-task-1",
        job_id="job-queued",
        document_id="doc-queued",
    )
    monitor = RedisGraphRAGQueueMonitor(
        redis_url="redis://unused/0",
        client=_FakeRedis(raw_message),
    )

    status = inspect_graphrag_status(
        enabled=True,
        queue_name="graphrag:jobs",
        control=_HealthyControl(started_at.timestamp()),  # type: ignore[arg-type]
        queue_monitor=monitor,
        now=started_at.replace(minute=2),
    )

    assert status.queued_jobs == 1
    assert status.queue_error is None
    assert status.queued_tasks[0].task_id == "queued-task-1"
    assert status.queued_tasks[0].job_id == "job-queued"
    assert status.active_tasks[0].started_at == started_at
    assert status.active_tasks[0].elapsed_seconds == 120


class _FailingControl:
    def snapshot(self, desired_concurrency: int) -> WorkerControlResult:
        _ = desired_concurrency
        raise TimeoutError("celery inspect timed out")


class _FailingQueueMonitor:
    def queue_length(self, queue_name: str) -> int:
        _ = queue_name
        raise ConnectionError("redis unavailable")

    def queued_tasks(self, queue_name: str, *, limit: int = 25):
        _ = (queue_name, limit)
        raise ConnectionError("redis unavailable")


class _HealthyControl:
    def __init__(self, time_start: float) -> None:
        self._time_start = time_start

    def snapshot(self, desired_concurrency: int) -> WorkerControlResult:
        return WorkerControlResult(
            desired_concurrency=desired_concurrency,
            workers=(
                WorkerCapacity(
                    name="graphrag-worker@test",
                    pool_size=1,
                    active_jobs=1,
                ),
            ),
            apply_status="applied",
            active_job_ids=frozenset({"job-active"}),
            active_tasks=(
                WorkerActiveTask(
                    task_id="active-task-1",
                    task_name="apps.ingestion.tasks.index_document_graphrag",
                    worker="graphrag-worker@test",
                    job_id="job-active",
                    doc_id="doc-active",
                    time_start=self._time_start,
                ),
            ),
        )


class _FakeRedis:
    def __init__(self, raw_message: bytes) -> None:
        self._raw_message = raw_message

    def llen(self, queue_name: str) -> int:
        assert queue_name == "graphrag:jobs"
        return 1

    def lrange(self, queue_name: str, start: int, end: int) -> list[bytes]:
        assert (queue_name, start, end) == ("graphrag:jobs", 0, 24)
        return [self._raw_message]


def _celery_message(*, task_id: str, job_id: str, document_id: str) -> bytes:
    body = base64.b64encode(
        json.dumps([[{"job_id": job_id, "doc_id": document_id}], {}, {}]).encode(
            "utf-8"
        )
    ).decode("ascii")
    return json.dumps(
        {
            "headers": {
                "id": task_id,
                "task": "apps.ingestion.tasks.index_document_graphrag",
            },
            "body": body,
        }
    ).encode("utf-8")
