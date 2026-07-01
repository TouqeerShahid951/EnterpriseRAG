from __future__ import annotations

from rag.services.ingest_worker_control import IngestWorkerControl


def test_snapshot_tracks_only_workers_subscribed_to_ingest_queue() -> None:
    app = _FakeCeleryApp()
    control = IngestWorkerControl(broker_url="redis://example/0", queue_name="ingest:jobs", app=app)

    snapshot = control.snapshot(desired_concurrency=2)

    assert [worker.name for worker in snapshot.workers] == ["ingestion-worker@node-a"]
    assert snapshot.observed_pool_size == 2
    assert snapshot.active_jobs == 1
    assert snapshot.active_job_ids == frozenset({"ingest-job-1"})
    assert len(snapshot.active_tasks) == 1
    assert snapshot.active_tasks[0].doc_id == "ingest-doc-1"


def test_snapshot_can_target_graphrag_queue_workers() -> None:
    app = _FakeCeleryApp()
    control = IngestWorkerControl(broker_url="redis://example/0", queue_name="graphrag:jobs", app=app)

    snapshot = control.snapshot(desired_concurrency=1)

    assert [worker.name for worker in snapshot.workers] == ["graphrag-worker@node-b"]
    assert snapshot.observed_pool_size == 1
    assert snapshot.active_jobs == 1
    assert snapshot.active_job_ids == frozenset({"graph-job-1"})
    assert snapshot.active_tasks[0].task_name == "apps.ingestion.tasks.index_document_graphrag"
    assert snapshot.active_tasks[0].doc_id == "graph-doc-1"


def test_apply_resizes_only_ingest_queue_workers() -> None:
    app = _FakeCeleryApp()
    control = IngestWorkerControl(broker_url="redis://example/0", queue_name="ingest:jobs", app=app)

    control.apply(desired_concurrency=3)

    assert app.control.grow_calls == [(1, ("ingestion-worker@node-a",))]
    assert app.control.shrink_calls == []


class _FakeCeleryApp:
    def __init__(self) -> None:
        self.control = _FakeControl()


class _FakeControl:
    def __init__(self) -> None:
        self.inspector = _FakeInspector()
        self.grow_calls: list[tuple[int, tuple[str, ...]]] = []
        self.shrink_calls: list[tuple[int, tuple[str, ...]]] = []

    def inspect(self, *, timeout: int):
        assert timeout == 2
        return self.inspector

    def pool_grow(self, difference: int, *, reply: bool, destination: list[str]) -> None:
        assert reply is True
        self.grow_calls.append((difference, tuple(destination)))

    def pool_shrink(self, difference: int, *, reply: bool, destination: list[str]) -> None:
        assert reply is True
        self.shrink_calls.append((difference, tuple(destination)))


class _FakeInspector:
    def stats(self) -> dict[str, dict[str, object]]:
        return {
            "ingestion-worker@node-a": {"pool": {"max-concurrency": 2, "processes": [11, 12, 13]}},
            "graphrag-worker@node-b": {"pool": {"max-concurrency": 1, "processes": [21]}},
            "evaluation-worker@node-c": {"pool": {"max-concurrency": 1, "processes": [31]}},
        }

    def active(self) -> dict[str, list[dict[str, object]]]:
        return {
            "ingestion-worker@node-a": [
                {
                    "id": "task-ingest-1",
                    "name": "apps.ingestion.tasks.ingest_document",
                    "args": [{"job_id": "ingest-job-1", "doc_id": "ingest-doc-1"}],
                    "time_start": 100.0,
                },
            ],
            "graphrag-worker@node-b": [
                {
                    "id": "task-graph-1",
                    "name": "apps.ingestion.tasks.index_document_graphrag",
                    "args": [{"job_id": "graph-job-1", "doc_id": "graph-doc-1"}],
                    "time_start": 120.0,
                },
            ],
            "evaluation-worker@node-c": [
                {"args": [{"job_id": "eval-job-should-not-count"}]},
            ],
        }

    def active_queues(self) -> dict[str, list[dict[str, str]]]:
        return {
            "ingestion-worker@node-a": [{"name": "ingest:jobs"}],
            "graphrag-worker@node-b": [{"name": "graphrag:jobs"}],
            "evaluation-worker@node-c": [{"name": "evaluation:jobs"}],
        }
