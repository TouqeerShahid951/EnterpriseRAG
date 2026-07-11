"""Celery task entrypoints for the ingestion runtime."""

from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from typing import Any

from apps.ingestion.celery_app import celery_app
from rag.graphrag.indexing import GraphRAGIndexingService, config_from_mapping
from rag.ingestion.config import WorkerConfig
from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.adapters.inference import build_ingestion_inference_client
from rag.ingestion.execution import _build_backend, run_ingest_document


@celery_app.task(bind=True, name="apps.ingestion.tasks.ingest_document")
def ingest_document(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@celery_app.task(bind=True, name="apps.ingestion.tasks.index_document_graphrag")
def index_document_graphrag(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    del self
    doc_id = str(payload.get("doc_id", "")).strip()
    job_id = str(payload.get("job_id", "")).strip()
    if not doc_id:
        return {"status": "skipped", "degraded_reason": "missing_doc_id"}
    config = WorkerConfig.from_env()
    if not config.graphrag_enabled:
        return {"status": "skipped", "doc_id": doc_id, "degraded_reason": "graphrag_disabled"}
    backend = _build_backend(config)
    runtime_config = backend.get_rag_config()
    inference = build_ingestion_inference_client(
        runtime_config,
        timeout_seconds=config.http_timeout_seconds,
        retry_base_seconds=config.ollama_retry_base_seconds,
        embedding_batch_size=config.embedding_batch_size,
        num_ctx=config.ollama_num_ctx,
    )
    graph_config = config_from_mapping(config)
    result = GraphRAGIndexingService(
        config=graph_config,
        inference=inference,
    ).index_document(doc_id)
    payload_out = asdict(result)
    if result.status == "complete" and result.partition_key and not graph_config.summarize_after_document:
        payload_out["partition_rebuild_status"] = _enqueue_partition_rebuild(
            config,
            partition_key=result.partition_key,
            doc_id=doc_id,
            job_id=job_id,
        )
    if job_id:
        _record_graphrag_event(config, job_id=job_id, result=payload_out)
    return payload_out


@celery_app.task(bind=True, name="apps.ingestion.tasks.rebuild_graphrag_partition")
def rebuild_graphrag_partition(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    del self
    partition_key = str(payload.get("partition_key", "")).strip()
    doc_id = str(payload.get("doc_id", "")).strip()
    job_id = str(payload.get("job_id", "")).strip()
    dedupe_key = str(payload.get("dedupe_key", "")).strip()
    if not partition_key:
        return {"status": "skipped", "doc_id": doc_id, "degraded_reason": "missing_partition_key"}
    config = WorkerConfig.from_env()
    try:
        if not config.graphrag_enabled:
            return {"status": "skipped", "doc_id": doc_id, "partition_key": partition_key, "degraded_reason": "graphrag_disabled"}
        backend = _build_backend(config)
        runtime_config = backend.get_rag_config()
        inference = build_ingestion_inference_client(
            runtime_config,
            timeout_seconds=config.http_timeout_seconds,
            retry_base_seconds=config.ollama_retry_base_seconds,
            embedding_batch_size=config.embedding_batch_size,
            num_ctx=config.ollama_num_ctx,
        )
        result = GraphRAGIndexingService(
            config=config_from_mapping(config),
            inference=inference,
        ).rebuild_partition(partition_key, doc_id=doc_id)
        payload_out = asdict(result)
        if job_id:
            _record_graphrag_event(config, job_id=job_id, result=payload_out)
        return payload_out
    finally:
        if dedupe_key:
            _clear_rebuild_marker(config, dedupe_key)


@celery_app.task(bind=True, name="apps.ingestion.tasks.reextract_document_metadata")
def reextract_document_metadata(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@celery_app.task(bind=True, name="apps.ingestion.tasks.reextract_document_topics")
def reextract_document_topics(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@celery_app.task(bind=True, name="apps.ingestion.tasks.reextract_document_claims")
def reextract_document_claims(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


@celery_app.task(bind=True, name="apps.ingestion.tasks.reextract_document_type")
def reextract_document_type(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return run_ingest_document(self, payload)


def _enqueue_partition_rebuild(
    config: WorkerConfig,
    *,
    partition_key: str,
    doc_id: str,
    job_id: str,
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
    marker_set = False
    try:
        marker_set = _set_rebuild_marker(config, dedupe_key, payload)
    except Exception:
        marker_set = True
        payload.pop("dedupe_key", None)
    if not marker_set:
        return "already_scheduled"
    try:
        rebuild_graphrag_partition.apply_async(
            args=[payload],
            queue=config.graphrag_queue_name,
            countdown=delay,
        )
    except Exception:
        _clear_rebuild_marker(config, dedupe_key)
        return "enqueue_failed"
    return "queued"


def _set_rebuild_marker(config: WorkerConfig, key: str, payload: dict[str, Any]) -> bool:
    from redis import Redis

    ttl = max(600, config.graphrag_partition_rebuild_delay_seconds + 600)
    client = Redis.from_url(config.redis_url, decode_responses=True)
    return bool(client.set(key, json.dumps(payload, ensure_ascii=True), nx=True, ex=ttl))


def _clear_rebuild_marker(config: WorkerConfig, key: str) -> None:
    try:
        from redis import Redis

        Redis.from_url(config.redis_url, decode_responses=True).delete(key)
    except Exception:
        pass


def _rebuild_marker_key(partition_key: str) -> str:
    digest = sha256(partition_key.encode("utf-8")).hexdigest()
    return f"graphrag:partition-rebuild:scheduled:{digest}"


def _record_graphrag_event(config: WorkerConfig, *, job_id: str, result: dict[str, Any]) -> None:
    try:
        _build_backend(config).record_event(
            job_id=job_id,
            event_type="graphrag_index",
            payload=result,
        )
    except ServiceRequestError:
        pass
