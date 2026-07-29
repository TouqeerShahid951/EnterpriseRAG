from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from rag.graphrag import maintenance_queue_dependencies
from rag.graphrag.adapters.maintenance_queue import (
    CeleryGraphRAGMaintenanceQueue,
    InMemoryGraphRAGMaintenanceQueue,
)
from rag.graphrag.maintenance_queue import (
    GraphRAGDocumentIndexMessage,
    GraphRAGPartitionRebuildMessage,
)

INDEX_TASK_NAME = "apps.ingestion.tasks.index_document_graphrag"
REBUILD_TASK_NAME = "apps.ingestion.tasks.rebuild_graphrag_partition"


@pytest.fixture(autouse=True)
def clear_dependency_cache() -> Iterator[None]:
    _clear_dependency_cache()
    yield
    _clear_dependency_cache()


class _FakeControl:
    def __init__(self) -> None:
        self.revocations: list[tuple[str, dict[str, object]]] = []
        self.error: Exception | None = None

    def revoke(self, task_id: str, **options: object) -> None:
        if self.error is not None:
            raise self.error
        self.revocations.append((task_id, options))


class _FakeCeleryApp:
    def __init__(self) -> None:
        self.control = _FakeControl()
        self.sent_tasks: list[tuple[str, list[dict[str, str]], str]] = []
        self.error: Exception | None = None

    def send_task(
        self,
        task_name: str,
        *,
        args: list[dict[str, str]],
        queue: str,
    ) -> None:
        if self.error is not None:
            raise self.error
        self.sent_tasks.append((task_name, args, queue))


def test_memory_adapter_records_each_operation_independently() -> None:
    queue = InMemoryGraphRAGMaintenanceQueue()
    document_message = GraphRAGDocumentIndexMessage(
        doc_id="doc-1",
        job_id="job-1",
        reason="user_request",
    )
    rebuild_message = GraphRAGPartitionRebuildMessage(
        doc_id="doc-1",
        partition_key="/ops",
        reason="document_deleted",
    )

    queue.enqueue_document_index(document_message)
    queue.enqueue_partition_rebuild(rebuild_message)
    queue.cancel("task-1", terminate=True)

    assert queue.document_messages == [document_message]
    assert queue.messages == [rebuild_message]
    assert queue.cancelled_tasks == [("task-1", True)]


def test_celery_adapter_preserves_document_and_rebuild_dispatch_contracts() -> None:
    app = _FakeCeleryApp()
    queue = _celery_queue(app)

    queue.enqueue_document_index(
        GraphRAGDocumentIndexMessage(
            doc_id="doc-1",
            job_id="job-1",
            reason="user_request",
            index_generation_id="generation-1",
        )
    )
    queue.enqueue_partition_rebuild(
        GraphRAGPartitionRebuildMessage(
            doc_id="doc-2",
            partition_key="/finance",
            reason="access_scope_changed",
        )
    )

    assert app.sent_tasks == [
        (
            INDEX_TASK_NAME,
            [
                {
                    "doc_id": "doc-1",
                    "job_id": "job-1",
                    "reason": "user_request",
                    "index_generation_id": "generation-1",
                }
            ],
            "graphrag:jobs",
        ),
        (
            REBUILD_TASK_NAME,
            [
                {
                    "doc_id": "doc-2",
                    "partition_key": "/finance",
                    "reason": "access_scope_changed",
                }
            ],
            "graphrag:jobs",
        ),
    ]


def test_celery_adapter_preserves_queued_and_running_cancellation_options() -> None:
    app = _FakeCeleryApp()
    queue = _celery_queue(app)

    queue.cancel("queued-task")
    queue.cancel("running-task", terminate=True)

    assert app.control.revocations == [
        ("queued-task", {"terminate": False}),
        ("running-task", {"terminate": True, "signal": "SIGTERM"}),
    ]


@pytest.mark.parametrize(
    ("operation", "expected_message"),
    [
        ("document", "graphrag document enqueue failed"),
        ("rebuild", "graphrag rebuild enqueue failed"),
    ],
)
def test_celery_adapter_wraps_dispatch_failures_with_operation_context(
    operation: str,
    expected_message: str,
) -> None:
    app = _FakeCeleryApp()
    app.error = ConnectionError("broker unavailable")
    queue = _celery_queue(app)

    with pytest.raises(RuntimeError, match=expected_message) as exc_info:
        if operation == "document":
            queue.enqueue_document_index(
                GraphRAGDocumentIndexMessage("doc-1", "job-1", "user_request")
            )
        else:
            queue.enqueue_partition_rebuild(
                GraphRAGPartitionRebuildMessage(
                    "doc-1",
                    "/ops",
                    "document_deleted",
                )
            )

    assert isinstance(exc_info.value.__cause__, ConnectionError)


def test_celery_adapter_wraps_cancellation_failure_with_context() -> None:
    app = _FakeCeleryApp()
    app.control.error = ConnectionError("broker unavailable")

    with pytest.raises(
        RuntimeError,
        match="graphrag task cancellation failed",
    ) as exc_info:
        _celery_queue(app).cancel("task-1")

    assert isinstance(exc_info.value.__cause__, ConnectionError)


def test_cached_dependency_returns_one_memory_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        maintenance_queue_dependencies.settings,
        "ingest_queue_backend",
        "memory",
    )

    first = maintenance_queue_dependencies.default_graphrag_maintenance_queue()
    second = maintenance_queue_dependencies.get_graphrag_maintenance_queue()

    assert isinstance(first, InMemoryGraphRAGMaintenanceQueue)
    assert second is first


@pytest.mark.parametrize(
    ("celery_broker_url", "expected_broker_url"),
    [
        ("redis://broker/0", "redis://broker/0"),
        (None, "redis://fallback/0"),
    ],
)
def test_dependency_passes_existing_settings_to_celery_adapter(
    monkeypatch: pytest.MonkeyPatch,
    celery_broker_url: str | None,
    expected_broker_url: str,
) -> None:
    captured: dict[str, Any] = {}

    class _CapturingQueue:
        def __init__(self, **options: Any) -> None:
            captured.update(options)

    monkeypatch.setattr(
        maintenance_queue_dependencies,
        "CeleryGraphRAGMaintenanceQueue",
        _CapturingQueue,
    )
    monkeypatch.setattr(
        maintenance_queue_dependencies.settings,
        "ingest_queue_backend",
        "celery",
    )
    monkeypatch.setattr(
        maintenance_queue_dependencies.settings,
        "celery_broker_url",
        celery_broker_url,
    )
    monkeypatch.setattr(
        maintenance_queue_dependencies.settings,
        "redis_url",
        "redis://fallback/0",
    )

    queue = maintenance_queue_dependencies.default_graphrag_maintenance_queue()

    assert isinstance(queue, _CapturingQueue)
    assert captured == {
        "broker_url": expected_broker_url,
        "queue_name": maintenance_queue_dependencies.settings.graphrag_queue_name,
        "index_task_name": maintenance_queue_dependencies.settings.graphrag_index_task_name,
        "rebuild_task_name": maintenance_queue_dependencies.settings.graphrag_partition_rebuild_task_name,
    }


def test_dependency_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        maintenance_queue_dependencies.settings,
        "ingest_queue_backend",
        "unsupported",
    )

    with pytest.raises(
        RuntimeError,
        match="unsupported GraphRAG maintenance queue backend: unsupported",
    ):
        maintenance_queue_dependencies.default_graphrag_maintenance_queue()


def _celery_queue(app: _FakeCeleryApp) -> CeleryGraphRAGMaintenanceQueue:
    return CeleryGraphRAGMaintenanceQueue(
        broker_url="redis://broker/0",
        queue_name="graphrag:jobs",
        index_task_name=INDEX_TASK_NAME,
        rebuild_task_name=REBUILD_TASK_NAME,
        app=app,
    )


def _clear_dependency_cache() -> None:
    maintenance_queue_dependencies.default_graphrag_maintenance_queue.cache_clear()
