"""Celery task entrypoints for the ingestion runtime."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from apps.ingestion.celery_app import celery_app
from rag.graphrag.indexing import GraphRAGIndexingService, config_from_mapping
from rag_ingestion.config import WorkerConfig
from rag_ingestion.infrastructure.http import ServiceRequestError
from rag_ingestion.infrastructure.inference import build_ingestion_inference_client
from rag_ingestion.service import _build_backend, run_ingest_document


@celery_app.task(bind=True, name="apps.ingestion.tasks.ingest_document")
def ingest_document(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    result = run_ingest_document(self, payload)
    _enqueue_graphrag_indexing(result)
    return result


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
    result = GraphRAGIndexingService(
        config=config_from_mapping(config),
        inference=inference,
    ).index_document(doc_id)
    payload_out = asdict(result)
    if job_id:
        _record_graphrag_event(config, job_id=job_id, result=payload_out)
    return payload_out


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


def _enqueue_graphrag_indexing(result: dict[str, Any]) -> None:
    if result.get("status") != "complete":
        return
    doc_id = str(result.get("doc_id", "")).strip()
    if not doc_id:
        return
    config = WorkerConfig.from_env()
    if not config.graphrag_enabled:
        return
    try:
        index_document_graphrag.apply_async(
            args=[{"doc_id": doc_id, "job_id": result.get("job_id", "")}],
            queue=config.graphrag_queue_name,
        )
    except Exception as exc:
        warnings = list(result.get("warnings") or [])
        warnings.append(f"graphrag_enqueue_failed:{str(exc)[:160]}")
        result["warnings"] = warnings


def _record_graphrag_event(config: WorkerConfig, *, job_id: str, result: dict[str, Any]) -> None:
    try:
        _build_backend(config).record_event(
            job_id=job_id,
            event_type="graphrag_index",
            payload=result,
        )
    except ServiceRequestError:
        pass
