"""Celery task adapters for ingestion and GraphRAG deliveries."""

from __future__ import annotations

from typing import Any, Callable

from billiard.exceptions import SoftTimeLimitExceeded

from rag.graphrag.task_execution import (
    run_document_graph_index,
    run_partition_rebuild,
)
from rag.ingestion.execution import IngestDeliveryRetry, run_ingest_document
from rag.shared.contracts.task_names import (
    DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
    DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
    DEFAULT_INGEST_TASK_NAME,
    REEXTRACT_DOCUMENT_CLAIMS_TASK_NAME,
    REEXTRACT_DOCUMENT_METADATA_TASK_NAME,
    REEXTRACT_DOCUMENT_TOPICS_TASK_NAME,
    REEXTRACT_DOCUMENT_TYPE_TASK_NAME,
)

from .celery_app import celery_app, config


TaskHandler = Callable[[Any, dict[str, Any]], dict[str, Any]]


def _run_ingest_delivery(task: Any, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return run_ingest_document(
            payload,
            timeout_error_types=(SoftTimeLimitExceeded,),
        )
    except IngestDeliveryRetry as retry:
        raise task.retry(
            exc=retry.cause,
            countdown=retry.countdown,
            max_retries=retry.max_retries,
        )


def _ingest_document(task: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return _run_ingest_delivery(task, payload)


def _reextract_document_metadata(
    task: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _run_ingest_delivery(task, payload)


def _reextract_document_topics(
    task: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _run_ingest_delivery(task, payload)


def _reextract_document_claims(
    task: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _run_ingest_delivery(task, payload)


def _reextract_document_type(
    task: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _run_ingest_delivery(task, payload)


def _index_document_graphrag(
    task: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    del task
    return run_document_graph_index(
        payload,
        dispatch_partition_rebuild=_dispatch_partition_rebuild,
    )


def _rebuild_graphrag_partition(
    task: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    del task
    return run_partition_rebuild(payload)


def _dispatch_partition_rebuild(
    payload: dict[str, Any],
    queue_name: str,
    countdown_seconds: int,
) -> None:
    rebuild_graphrag_partition.apply_async(
        args=[payload],
        queue=queue_name,
        countdown=countdown_seconds,
    )


def _register_task(name: str, handler: TaskHandler) -> Any:
    return celery_app.task(
        bind=True,
        name=name,
        max_retries=3,
        shared=False,
        lazy=False,
    )(handler)


def _register_compatible_task(
    configured_name: str,
    historic_name: str,
    handler: TaskHandler,
) -> Any:
    task = _register_task(configured_name, handler)
    if configured_name != historic_name:
        _register_task(historic_name, handler)
    return task


ingest_document = _register_compatible_task(
    config.ingest_task_name,
    DEFAULT_INGEST_TASK_NAME,
    _ingest_document,
)
reextract_document_metadata = _register_task(
    REEXTRACT_DOCUMENT_METADATA_TASK_NAME,
    _reextract_document_metadata,
)
reextract_document_topics = _register_task(
    REEXTRACT_DOCUMENT_TOPICS_TASK_NAME,
    _reextract_document_topics,
)
reextract_document_claims = _register_task(
    REEXTRACT_DOCUMENT_CLAIMS_TASK_NAME,
    _reextract_document_claims,
)
reextract_document_type = _register_task(
    REEXTRACT_DOCUMENT_TYPE_TASK_NAME,
    _reextract_document_type,
)
index_document_graphrag = _register_compatible_task(
    config.graphrag_index_task_name,
    DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
    _index_document_graphrag,
)
rebuild_graphrag_partition = _register_compatible_task(
    config.graphrag_partition_rebuild_task_name,
    DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
    _rebuild_graphrag_partition,
)
