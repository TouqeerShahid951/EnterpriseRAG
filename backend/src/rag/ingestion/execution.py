"""Ingestion task execution for RAG documents."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import uuid4

from billiard.exceptions import SoftTimeLimitExceeded
from rag.ingestion.quality import parser_tuning_for_quality_preset

from .adapters.backend import BackendInternalClient, IngestAttempt
from .adapters.http import ServiceRequestError
from .adapters.inference import build_ingestion_inference_client
from .adapters.ollama import is_transient_service_error
from .adapters.storage import DocumentImageAssetWriter, UploadObjectReader
from .adapters.vision import OPENAI_COMPATIBLE_PROVIDER, OLLAMA_PROVIDER, VisionClient
from .config import WorkerConfig
from .errors import EmbeddingUnavailable, HumanReviewRequired, IngestJobCancelled, WorkerStepError
from .indexing.qdrant import QdrantClient
from .indexing.sparse import SparseEmbedder
from .contracts import IngestJobPayload
from .pipeline import IngestDependencies, run_ingest_graph


def run_ingest_document(task: Any, payload: dict[str, Any]) -> dict[str, Any]:
    job = IngestJobPayload.from_dict(payload)
    config = WorkerConfig.from_env()
    backend = _build_backend(config)
    run_token = str(uuid4())
    attempt = _start_attempt(task, backend, job.job_id, run_token)
    if not attempt.accepted:
        resume_attempt = _resume_exhausted_review_attempt(
            backend,
            job,
            attempt,
            run_token,
        )
        if resume_attempt is None:
            return _handle_rejected_attempt(backend, job, attempt)
        attempt = resume_attempt

    deps: IngestDependencies | None = None
    try:
        with _job_heartbeat(backend, job.job_id, config.heartbeat_interval_seconds):
            deps = _build_dependencies(config, backend=backend, quality_preset=job.quality_preset)
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
    except EmbeddingUnavailable as exc:
        return _retry_or_fail(
            task,
            config=config,
            backend=backend,
            job=job,
            attempt=attempt,
            exc=exc,
            error_code="embedding_unavailable",
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
        lease_lost = _mark_failed_or_lease_lost(
            backend,
            job=job,
            error_code=exc.code,
            error_message_safe=exc.safe_message,
        )
        if lease_lost is not None:
            return lease_lost
        raise
    except ServiceRequestError as exc:
        if _is_lease_lost(exc):
            return _lease_lost_result(job)
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
        lease_lost = _mark_failed_or_lease_lost(
            backend,
            job=job,
            error_code=f"{exc.service}_failed",
            error_message_safe=exc.message[:500],
        )
        if lease_lost is not None:
            return lease_lost
        raise
    except Exception as exc:
        if _job_is_cancelled(backend, job.job_id):
            return _cancelled_result(config, backend=backend, job=job, deps=deps)
        lease_lost = _mark_failed_or_lease_lost(
            backend,
            job=job,
            error_code="ingest_failed",
            error_message_safe=str(exc)[:500],
        )
        if lease_lost is not None:
            return lease_lost
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


def _resume_exhausted_review_attempt(
    backend: BackendInternalClient,
    job: IngestJobPayload,
    attempt: IngestAttempt,
    run_token: str,
) -> IngestAttempt | None:
    if not (job.review_batch_id or job.image_review_batch_id):
        return None
    if attempt.disposition != "exhausted" or attempt.job_status != "queued" or attempt.attempt_count < attempt.max_attempts:
        return None
    try:
        updated = _update_job_best_effort(
            backend,
            job_id=job.job_id,
            status="processing",
            progress_pct=5,
            error_code=None,
            error_message_safe=None,
            run_token=run_token,
        )
    except ServiceRequestError as exc:
        if _is_lease_lost(exc):
            return None
        raise
    if not updated:
        return None
    _record_event(
        backend,
        job.job_id,
        "review_resume_after_retry_limit",
        {"attempt_count": attempt.attempt_count, "max_attempts": attempt.max_attempts},
    )
    return IngestAttempt(
        accepted=True,
        disposition="review_resume",
        attempt_count=attempt.attempt_count,
        max_attempts=attempt.max_attempts,
        job_status="processing",
        run_token=run_token,
    )


def _start_attempt(
    task: Any,
    backend: BackendInternalClient,
    job_id: str,
    run_token: str,
) -> IngestAttempt:
    try:
        return backend.start_attempt(job_id=job_id, run_token=run_token)
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
        try:
            _update_job_best_effort(
                backend,
                job_id=job.job_id,
                status="failed",
                progress_pct=100,
                error_code=error_code,
                error_message_safe=str(exc)[:500],
            )
        except ServiceRequestError as lease_exc:
            if _is_lease_lost(lease_exc):
                return _lease_lost_result(job)
            raise
        _record_event(
            backend,
            job.job_id,
            "exhausted",
            {"error_code": error_code, "attempt_count": attempt.attempt_count},
        )
        raise exc

    countdown = 30 * (2 ** (attempt.attempt_count - 1))
    try:
        requeued = _update_job_best_effort(
            backend,
            job_id=job.job_id,
            status="queued",
            progress_pct=0,
            error_code=None,
            error_message_safe=None,
        )
    except ServiceRequestError as lease_exc:
        if _is_lease_lost(lease_exc):
            return _lease_lost_result(job)
        raise
    retry_countdown = _retry_countdown(config, countdown, requeued=requeued)
    _record_event(
        backend,
        job.job_id,
        "retry",
        {
            "error_code": error_code,
            "attempt_count": attempt.attempt_count,
            "next_attempt": attempt.attempt_count + 1,
            "countdown_seconds": retry_countdown,
            "status_requeued": requeued,
        },
    )
    raise task.retry(exc=exc, countdown=retry_countdown, max_retries=None)


def _retry_countdown(config: WorkerConfig, base_countdown: int, *, requeued: bool) -> int:
    if requeued:
        return base_countdown
    stale_after = max(0, int(getattr(config, "ingest_stale_after_seconds", 120)))
    return max(base_countdown, stale_after + 5)


def _update_job_best_effort(
    backend: BackendInternalClient,
    *,
    job_id: str,
    status: str,
    progress_pct: int,
    stage_progress: dict[str, object] | None = None,
    error_code: str | None = None,
    error_message_safe: str | None = None,
    warnings: list[str] | None = None,
    run_token: str | None = None,
) -> bool:
    try:
        backend.update_job(
            job_id=job_id,
            status=status,
            progress_pct=progress_pct,
            stage_progress=stage_progress,
            error_code=error_code,
            error_message_safe=error_message_safe,
            warnings=warnings,
            run_token=run_token,
        )
    except ServiceRequestError as exc:
        if _is_lease_lost(exc):
            raise
        return False
    return True


def _mark_failed_or_lease_lost(
    backend: BackendInternalClient,
    *,
    job: IngestJobPayload,
    error_code: str,
    error_message_safe: str,
) -> dict[str, Any] | None:
    try:
        backend.update_job(
            job_id=job.job_id,
            status="failed",
            progress_pct=100,
            error_code=error_code,
            error_message_safe=error_message_safe,
        )
    except ServiceRequestError as exc:
        if _is_lease_lost(exc):
            return _lease_lost_result(job)
        raise
    return None


def _is_lease_lost(exc: ServiceRequestError) -> bool:
    return exc.status_code == 409 and "ingest_job_lease_lost" in exc.message


def _lease_lost_result(job: IngestJobPayload) -> dict[str, Any]:
    return {"job_id": job.job_id, "doc_id": job.doc_id, "status": "lease_lost"}


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
            except ServiceRequestError as exc:
                if _is_lease_lost(exc):
                    return
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


def _build_dependencies(
    config: WorkerConfig,
    *,
    backend: BackendInternalClient | None = None,
    quality_preset: str | None = None,
) -> IngestDependencies:
    backend = backend or _build_backend(config)
    inference_config = backend.get_rag_config()
    ingest_config = backend.get_ingest_config()
    parser_tuning = parser_tuning_for_quality_preset(
        quality_preset or ingest_config.quality_preset or config.ingestion_quality_preset,
        weak_page_threshold=config.weak_page_threshold,
        full_doc_weak_page_ratio=config.full_doc_weak_page_ratio,
        layered_docling_max_pages=config.layered_docling_max_pages,
    )
    return IngestDependencies(
        backend=backend,
        storage=UploadObjectReader(config.minio),
        image_asset_writer=DocumentImageAssetWriter(config.minio),
        ollama=build_ingestion_inference_client(
            inference_config,
            timeout_seconds=config.http_timeout_seconds,
            retry_base_seconds=config.ollama_retry_base_seconds,
            embedding_batch_size=config.embedding_batch_size,
            dense_cache_dir=config.model_provider.dense_cache_dir,
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
        ingestion_quality_preset=parser_tuning.quality_preset,
        weak_page_threshold=parser_tuning.weak_page_threshold,
        full_doc_weak_page_ratio=parser_tuning.full_doc_weak_page_ratio,
        layered_docling_max_pages=parser_tuning.layered_docling_max_pages,
        layered_docling_max_page_ratio=parser_tuning.layered_docling_max_page_ratio,
        prefer_full_document_docling=parser_tuning.prefer_full_document_docling,
        layered_docling_batch_pages=config.layered_docling_batch_pages,
        pdf_image_analysis_max_images=config.pdf_image_analysis_max_images,
        pdf_image_analysis_max_full_page_fallbacks=config.pdf_image_analysis_max_full_page_fallbacks,
        pdf_image_review_threshold=ingest_config.pdf_image_review_threshold,
        scanned_visual_region_enabled=config.scanned_visual_region_enabled,
        scanned_visual_min_area_ratio=config.scanned_visual_min_area_ratio,
        scanned_visual_max_regions_per_page=config.scanned_visual_max_regions_per_page,
        scanned_visual_text_mask_padding_px=config.scanned_visual_text_mask_padding_px,
        ocr_review_confidence_threshold=ingest_config.ocr_review_confidence_threshold,
        vision_layout_repair_enabled=ingest_config.vision_layout_repair_enabled,
    )


def _build_vision_client(config: WorkerConfig, runtime_config: object) -> VisionClient:
    provider = str(
        getattr(runtime_config, "vision_provider", None)
        or getattr(runtime_config, "ingestion_provider", None)
        or getattr(runtime_config, "provider", "")
    ).strip().lower()
    if provider == OLLAMA_PROVIDER:
        return VisionClient(
            provider=OLLAMA_PROVIDER,
            base_url=str(
                getattr(runtime_config, "vision_base_url", None)
                or getattr(runtime_config, "ingestion_base_url", None)
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
        base_url=str(getattr(runtime_config, "vision_base_url", None) or config.vision.base_url),
        model=str(getattr(runtime_config, "vision_model", None) or config.vision.model),
        timeout_seconds=config.http_timeout_seconds,
    )
