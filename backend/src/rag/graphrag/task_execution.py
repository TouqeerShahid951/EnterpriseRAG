"""Execute GraphRAG worker workflows independently of Celery composition."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from typing import Any

from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.adapters.inference import build_ingestion_inference_client
from rag.ingestion.config import WorkerConfig
from rag.ingestion.execution import build_backend_client

from .indexing import GraphRAGIndexingService, config_from_mapping


logger = logging.getLogger("rag.graphrag.task_execution")
PartitionRebuildDispatcher = Callable[[dict[str, Any], str, int], None]


class GraphRAGDeliveryRetry(RuntimeError):
    """Request that the queue transport redeliver GraphRAG work."""

    def __init__(self, cause: Exception, *, countdown: int = 30) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.countdown = countdown


def run_document_graph_index(
    payload: dict[str, Any],
    *,
    dispatch_partition_rebuild: PartitionRebuildDispatcher,
) -> dict[str, Any]:
    doc_id = str(payload.get("doc_id", "")).strip()
    job_id = str(payload.get("job_id", "")).strip()
    index_generation_id = str(payload.get("index_generation_id") or "").strip()
    if not doc_id:
        return {"status": "skipped", "degraded_reason": "missing_doc_id"}

    config = WorkerConfig.from_env()
    if not config.graphrag_enabled:
        return {
            "status": "skipped",
            "doc_id": doc_id,
            "degraded_reason": "graphrag_disabled",
        }

    backend = build_backend_client(config)
    runtime_config = backend.get_rag_config()
    inference = _build_graph_inference(config, runtime_config)
    graph_config = config_from_mapping(config)
    result = GraphRAGIndexingService(
        config=graph_config,
        inference=inference,
    ).index_document(
        doc_id,
        index_generation_id=index_generation_id or None,
    )
    result_payload = asdict(result)
    if (
        result.status == "complete"
        and result.partition_key
        and not graph_config.summarize_after_document
    ):
        result_payload["partition_rebuild_status"] = _enqueue_partition_rebuild(
            config,
            partition_key=result.partition_key,
            doc_id=doc_id,
            job_id=job_id,
            dispatch=dispatch_partition_rebuild,
        )
    if job_id:
        _record_graphrag_event(config, job_id=job_id, result=result_payload)
    return _retry_degraded_result(result_payload)


def run_partition_rebuild(payload: dict[str, Any]) -> dict[str, Any]:
    partition_key = str(payload.get("partition_key", "")).strip()
    doc_id = str(payload.get("doc_id", "")).strip()
    job_id = str(payload.get("job_id", "")).strip()
    dedupe_key = str(payload.get("dedupe_key", "")).strip()
    if not partition_key:
        return {
            "status": "skipped",
            "doc_id": doc_id,
            "degraded_reason": "missing_partition_key",
        }

    config = WorkerConfig.from_env()
    try:
        if not config.graphrag_enabled:
            return {
                "status": "skipped",
                "doc_id": doc_id,
                "partition_key": partition_key,
                "degraded_reason": "graphrag_disabled",
            }
        backend = build_backend_client(config)
        runtime_config = backend.get_rag_config()
        inference = _build_graph_inference(config, runtime_config)
        result = GraphRAGIndexingService(
            config=config_from_mapping(config),
            inference=inference,
        ).rebuild_partition(partition_key, doc_id=doc_id)
        result_payload = asdict(result)
        if job_id:
            _record_graphrag_event(config, job_id=job_id, result=result_payload)
        return _retry_degraded_result(result_payload)
    finally:
        if dedupe_key:
            _clear_rebuild_marker(config, dedupe_key)


def _enqueue_partition_rebuild(
    config: WorkerConfig,
    *,
    partition_key: str,
    doc_id: str,
    job_id: str,
    dispatch: PartitionRebuildDispatcher,
) -> str:
    dedupe_key = _rebuild_marker_key(partition_key)
    delay = config.graphrag_partition_rebuild_delay_seconds
    payload = {
        "doc_id": doc_id,
        "job_id": job_id,
        "partition_key": partition_key,
        "dedupe_key": dedupe_key,
        "reason": "document_index",
    }
    try:
        marker_set = _set_rebuild_marker(config, dedupe_key, payload)
    except Exception:
        logger.warning(
            "GraphRAG rebuild deduplication unavailable; scheduling without a marker "
            "doc_id=%s job_id=%s marker_key=%s",
            doc_id,
            job_id,
            dedupe_key,
            exc_info=True,
        )
        marker_set = True
        payload.pop("dedupe_key", None)
    if not marker_set:
        return "already_scheduled"

    try:
        dispatch(payload, config.graphrag_queue_name, delay)
    except Exception:
        logger.exception(
            "GraphRAG partition rebuild enqueue failed doc_id=%s job_id=%s marker_key=%s",
            doc_id,
            job_id,
            dedupe_key,
        )
        _clear_rebuild_marker(config, dedupe_key)
        return "enqueue_failed"
    return "queued"


def _build_graph_inference(config: WorkerConfig, runtime_config: object) -> object:
    return build_ingestion_inference_client(
        runtime_config,
        timeout_seconds=config.http_timeout_seconds,
        retry_base_seconds=config.ollama_retry_base_seconds,
        embedding_batch_size=config.embedding_batch_size,
        dense_cache_dir=config.local_embeddings.dense_cache_dir,
        num_ctx=config.ollama_num_ctx,
    )


def _set_rebuild_marker(
    config: WorkerConfig,
    key: str,
    payload: dict[str, Any],
) -> bool:
    from redis import Redis

    ttl = max(600, config.graphrag_partition_rebuild_delay_seconds + 600)
    client = Redis.from_url(config.redis_url, decode_responses=True)
    return bool(client.set(key, json.dumps(payload, ensure_ascii=True), nx=True, ex=ttl))


def _clear_rebuild_marker(config: WorkerConfig, key: str) -> None:
    try:
        from redis import Redis

        Redis.from_url(config.redis_url, decode_responses=True).delete(key)
    except Exception:
        logger.warning(
            "GraphRAG rebuild marker cleanup failed marker_key=%s",
            key,
            exc_info=True,
        )


def _rebuild_marker_key(partition_key: str) -> str:
    digest = sha256(partition_key.encode("utf-8")).hexdigest()
    return f"graphrag:partition-rebuild:scheduled:{digest}"


def _record_graphrag_event(
    config: WorkerConfig,
    *,
    job_id: str,
    result: dict[str, Any],
) -> None:
    try:
        build_backend_client(config).record_event(
            job_id=job_id,
            event_type="graphrag_index",
            payload=result,
        )
    except ServiceRequestError:
        logger.warning(
            "GraphRAG indexing event could not be recorded job_id=%s status=%s",
            job_id,
            result.get("status", "unknown"),
            exc_info=True,
        )


def _retry_degraded_result(result: dict[str, Any]) -> dict[str, Any]:
    reason = str(result.get("degraded_reason") or "").strip()
    rebuild_enqueue_failed = (
        result.get("partition_rebuild_status") == "enqueue_failed"
    )
    if rebuild_enqueue_failed:
        reason = reason or "GraphRAG partition rebuild could not be queued"
    if result.get("status") == "degraded" or rebuild_enqueue_failed:
        raise GraphRAGDeliveryRetry(
            RuntimeError(reason or "GraphRAG processing was degraded")
        )
    return result
