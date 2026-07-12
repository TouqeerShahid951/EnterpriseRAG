"""Celery task adapters for GraphRAG indexing workflows."""

from __future__ import annotations

from typing import Any

from celery import shared_task

from .task_execution import run_document_graph_index, run_partition_rebuild


@shared_task(bind=True, name="apps.ingestion.tasks.index_document_graphrag")
def index_document_graphrag(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    del self
    return run_document_graph_index(
        payload,
        dispatch_partition_rebuild=_dispatch_partition_rebuild,
    )


@shared_task(bind=True, name="apps.ingestion.tasks.rebuild_graphrag_partition")
def rebuild_graphrag_partition(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    del self
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
