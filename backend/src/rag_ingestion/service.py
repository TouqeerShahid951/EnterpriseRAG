"""Ingestion task execution for RAG documents."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from billiard.exceptions import SoftTimeLimitExceeded

from .infrastructure.backend import BackendInternalClient, IngestAttempt
from .infrastructure.http import ServiceRequestError
from .infrastructure.inference import build_ingestion_inference_client
from .infrastructure.ollama import is_transient_service_error
from .infrastructure.storage import DocumentImageAssetWriter, UploadObjectReader
from .infrastructure.vision import OPENAI_COMPATIBLE_PROVIDER, OLLAMA_PROVIDER, VisionClient
from .config import WorkerConfig
from .errors import HumanReviewRequired, IngestJobCancelled, OllamaEmbeddingUnavailable, WorkerStepError
from .indexing.qdrant import QdrantClient
from .indexing.sparse import SparseEmbedder
from .messages import IngestJobPayload
from .stages import IngestDependencies, run_ingest_graph


def run_ingest_document(task: Any, payload: dict[str, Any]) -> dict[str, Any]:
    job = IngestJobPayload.from_dict(payload)
    config = WorkerConfig.from_env()
    backend = _build_backend(config)
    attempt = _start_attempt(task, backend, job.job_id)
    if not attempt.accepted:
        return _handle_rejected_attempt(backend, job, attempt)

    deps: IngestDependencies | None = None
    try:
        with _job_heartbeat(backend, job.job_id, config.heartbeat_interval_seconds):
            deps = _build_dependencies(config, backend=backend)
            state = run_ingest_graph(job, deps)
    except HumanReviewRequired as exc:
        return {
            "job_id": job.job_id,
            "doc_id": job.doc_id,
            "status": "human_review",
            "review_batch_id": exc.review_batch_id,
        }
    except IngestJobCancelled:
        return _cancelled_result(config, backend=backend, job=job, deps=deps)
    except OllamaEmbeddingUnavailable as exc:
        return _retry_or_fail(
            task,
            config=config,
            backend=backend,
            job=job,
            attempt=attempt,
            exc=exc,
            error_code="ollama_embedding_unavailable",
        )
    except SoftTimeLimitExceeded as exc:
        return _retry_or_fail(
            task,
            config=config,
            backend=backend,
            job=job,
            attempt=attempt,
            exc=exc,
            error_code="ingest_timeout",
        )
    except WorkerStepError as exc:
        if _job_is_cancelled(backend, job.job_id):
            return _cancelled_result(config, backend=backend, job=job, deps=deps)
        backend.update_job(
            job_id=job.job_id,
            status="failed",
            progress_pct=100,
            error_code=exc.code,
            error_message_safe=exc.safe_message,
        )
        raise
    except ServiceRequestError as exc:
        if is_transient_service_error(exc):
            return _retry_or_fail(
                task,
                config=config,
                backend=backend,
                job=job,
                attempt=attempt,
                exc=exc,
                error_code=f"{exc.service}_unavailable",
            )
        if _job_is_cancelled(backend, job.job_id):
            return _cancelled_result(config, backend=backend, job=job, deps=deps)
        backend.update_job(
            job_id=job.job_id,
            status="failed",
            progress_pct=100,
            error_code=f"{exc.service}_failed",
            error_message_safe=exc.message[:500],
        )
        raise
    except Exception as exc:
        if _job_is_cancelled(backend, job.job_id):
            return _cancelled_result(config, backend=backend, job=job, deps=deps)
        backend.update_job(
            job_id=job.job_id,
            status="failed",
            progress_pct=100,
            error_code="ingest_failed",
            error_message_safe=str(exc)[:500],
        )
        raise
    return {
        "job_id": job.job_id,
        "doc_id": job.doc_id,
        "status": "complete",
        "chunks_indexed": state.get("upsert_count", 0),
        "warnings": state.get("warnings", []),
    }


def _handle_rejected_attempt(
    backend: BackendInternalClient,
    job: IngestJobPayload,
    attempt: IngestAttempt,
) -> dict[str, Any]:
    if attempt.job_status in {"complete", "failed", "human_review", "cancelled"}:
        return {"job_id": job.job_id, "doc_id": job.doc_id, "status": attempt.job_status}
    if attempt.disposition == "busy":
        return {"job_id": job.job_id, "doc_id": job.doc_id, "status": "duplicate_ignored"}
    backend.update_job(
        job_id=job.job_id,
        status="failed",
        progress_pct=100,
        error_code="retry_exhausted",
        error_message_safe="Ingestion could not complete after three attempts.",
    )
    _record_event(
        backend,
        job.job_id,
        "exhausted",
        {"attempt_count": attempt.attempt_count, "max_attempts": attempt.max_attempts},
    )
    return {"job_id": job.job_id, "doc_id": job.doc_id, "status": "failed", "error_code": "retry_exhausted"}


def _start_attempt(task: Any, backend: BackendInternalClient, job_id: str) -> IngestAttempt:
    try:
        return backend.start_attempt(job_id=job_id)
    except ServiceRequestError as exc:
        if is_transient_service_error(exc):
            raise task.retry(exc=exc, countdown=30, max_retries=12)
        raise


def _retry_or_fail(
    task: Any,
    *,
    config: WorkerConfig,
    backend: BackendInternalClient,
    job: IngestJobPayload,
    attempt: IngestAttempt,
    exc: Exception,
    error_code: str,
) -> dict[str, Any]:
    if _job_is_cancelled(backend, job.job_id):
        return _cancelled_result(config, backend=backend, job=job)
    if attempt.attempt_count >= attempt.max_attempts:
        backend.update_job(
            job_id=job.job_id,
            status="failed",
            progress_pct=100,
            error_code=error_code,
            error_message_safe=str(exc)[:500],
        )
        _record_event(
            backend,
            job.job_id,
            "exhausted",
            {"error_code": error_code, "attempt_count": attempt.attempt_count},
        )
        raise exc

    countdown = 30 * (2 ** (attempt.attempt_count - 1))
    backend.update_job(
        job_id=job.job_id,
        status="queued",
        progress_pct=0,
        error_code=None,
        error_message_safe=None,
    )
    _record_event(
        backend,
        job.job_id,
        "retry",
        {
            "error_code": error_code,
            "attempt_count": attempt.attempt_count,
            "next_attempt": attempt.attempt_count + 1,
            "countdown_seconds": countdown,
        },
    )
    raise task.retry(exc=exc, countdown=countdown, max_retries=None)


def _cancelled_result(
    config: WorkerConfig,
    *,
    backend: BackendInternalClient,
    job: IngestJobPayload,
    deps: IngestDependencies | None = None,
) -> dict[str, Any]:
    _cleanup_cancelled_vectors(config, backend=backend, job=job, deps=deps)
    return {"job_id": job.job_id, "doc_id": job.doc_id, "status": "cancelled"}


def _job_is_cancelled(backend: BackendInternalClient, job_id: str) -> bool:
    try:
        return backend.get_job_status(job_id=job_id).status == "cancelled"
    except ServiceRequestError:
        return False


def _cleanup_cancelled_vectors(
    config: WorkerConfig,
    *,
    backend: BackendInternalClient,
    job: IngestJobPayload,
    deps: IngestDependencies | None = None,
) -> None:
    qdrant = deps.qdrant if deps is not None else QdrantClient(
        base_url=config.qdrant.url,
        collection=config.qdrant.collection,
        timeout_seconds=config.http_timeout_seconds,
        upsert_batch_size=config.qdrant.upsert_batch_size,
    )
    try:
        qdrant.delete_document_points(job.doc_id)
    except ServiceRequestError as exc:
        _record_event(
            backend,
            job.job_id,
            "cancel_cleanup_failed",
            {"component": "qdrant", "message": exc.message[:300]},
        )


def _record_event(backend: BackendInternalClient, job_id: str, event_type: str, payload: dict[str, object]) -> None:
    try:
        backend.record_event(job_id=job_id, event_type=event_type, payload=payload)
    except ServiceRequestError:
        pass


@contextmanager
def _job_heartbeat(
    backend: BackendInternalClient,
    job_id: str,
    interval_seconds: float,
) -> Iterator[None]:
    stopped = threading.Event()

    def send_heartbeats() -> None:
        while not stopped.wait(max(1, interval_seconds)):
            try:
                backend.heartbeat(job_id=job_id)
            except ServiceRequestError:
                continue

    thread = threading.Thread(target=send_heartbeats, name=f"ingest-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)


def _build_backend(config: WorkerConfig) -> BackendInternalClient:
    return BackendInternalClient(
        base_url=config.backend.internal_url,
        service_token=config.backend.service_token,
        timeout_seconds=config.http_timeout_seconds,
    )


def _build_dependencies(config: WorkerConfig, *, backend: BackendInternalClient | None = None) -> IngestDependencies:
    backend = backend or _build_backend(config)
    inference_config = backend.get_rag_config()
    ingest_config = backend.get_ingest_config()
    return IngestDependencies(
        backend=backend,
        storage=UploadObjectReader(config.minio),
        image_asset_writer=DocumentImageAssetWriter(config.minio),
        ollama=build_ingestion_inference_client(
            inference_config,
            timeout_seconds=config.http_timeout_seconds,
            retry_base_seconds=config.ollama_retry_base_seconds,
            embedding_batch_size=config.embedding_batch_size,
            num_ctx=config.ollama_num_ctx,
        ),
        sparse_embedder=SparseEmbedder(
            model_name=config.model_provider.sparse_model,
            cache_dir=config.model_provider.sparse_cache_dir,
        ),
        qdrant=QdrantClient(
            base_url=config.qdrant.url,
            collection=config.qdrant.collection,
            timeout_seconds=config.http_timeout_seconds,
            upsert_batch_size=config.qdrant.upsert_batch_size,
        ),
        vision=_build_vision_client(config, inference_config),
        min_chars_per_page=config.native_text_min_chars_per_page,
        chunk_target_tokens=config.chunk_target_tokens,
        chunk_overlap_tokens=config.chunk_overlap_tokens,
        parent_max_tokens=config.parent_max_tokens,
        metadata_use_gliner=config.metadata_use_gliner,
        topic_taxonomy=config.topic_taxonomy,
        weak_page_threshold=config.weak_page_threshold,
        full_doc_weak_page_ratio=config.full_doc_weak_page_ratio,
        layered_docling_max_pages=config.layered_docling_max_pages,
        layered_docling_batch_pages=config.layered_docling_batch_pages,
        ocr_review_confidence_threshold=ingest_config.ocr_review_confidence_threshold,
    )


def _build_vision_client(config: WorkerConfig, runtime_config: object) -> VisionClient:
    provider = str(getattr(runtime_config, "provider", "")).strip().lower()
    if provider == OLLAMA_PROVIDER:
        return VisionClient(
            provider=OLLAMA_PROVIDER,
            base_url=str(
                getattr(runtime_config, "ingestion_base_url", None)
                or getattr(runtime_config, "base_url", "")
            ),
            model=str(
                getattr(runtime_config, "vision_model", None)
                or config.vision.ollama_model
                or getattr(runtime_config, "ingestion_model", None)
                or getattr(runtime_config, "chat_model", "")
            ),
            timeout_seconds=config.http_timeout_seconds,
            num_ctx=config.vision.ollama_num_ctx,
        )
    return VisionClient(
        provider=OPENAI_COMPATIBLE_PROVIDER,
        base_url=config.vision.base_url,
        model=str(getattr(runtime_config, "vision_model", None) or config.vision.model),
        timeout_seconds=config.http_timeout_seconds,
    )
