"""Public ingestion-stage facade and parse/metadata orchestration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import threading
import time

from ..errors import HumanReviewRequired, IngestJobCancelled
from ..metadata import build_metadata_bundle, generate_metadata_v2
from ..parsers import PdfImageReviewRequired, parse_document, resume_pdf_image_review
from ..parsers.models import (
    ParsedPdfItem,
    parsed_image_asset_to_dict,
    parsed_item_from_dict,
    parsed_item_to_dict,
)
from .image_review import (
    image_review_candidates as _image_review_candidates,
    image_review_required_provenance as _image_review_required_provenance,
    image_review_resume_inputs as _image_review_resume_inputs,
)
from .indexing_stages import (
    activate_generation as activate_generation,
    chunk_text as chunk_text,
    download_file as download_file,
    embed_chunks as embed_chunks,
    mark_processing as mark_processing,
    upsert_qdrant as upsert_qdrant,
)
from .parser_diagnostics import parser_failure_provenance as _parser_failure_provenance
from .progress import (
    IMAGE_PROGRESS_END as IMAGE_PROGRESS_END,
    IMAGE_PROGRESS_START as IMAGE_PROGRESS_START,
    METADATA_PROGRESS_END as METADATA_PROGRESS_END,
    METADATA_PROGRESS_START as METADATA_PROGRESS_START,
    PARSE_PROGRESS_COMPLETE as PARSE_PROGRESS_COMPLETE,
    docling_progress_label as _docling_progress_label,
    docling_progress_reporter as _docling_progress_reporter,
    duration_label as _duration_label,
    image_progress_reporter as _image_progress_reporter,
    items_progress as _items_progress,
    page_count as _page_count,
    page_progress_reporter as _page_progress_reporter,
    raise_if_job_cancelled as _raise_if_job_cancelled,
    vision_layout_progress_reporter as _vision_layout_progress_reporter,
)
from .state import IngestDependencies, IngestState

METADATA_PROGRESS_INTERVAL_SECONDS = 15.0

__all__ = [
    "IMAGE_PROGRESS_END",
    "IMAGE_PROGRESS_START",
    "METADATA_PROGRESS_END",
    "METADATA_PROGRESS_INTERVAL_SECONDS",
    "METADATA_PROGRESS_START",
    "PARSE_PROGRESS_COMPLETE",
    "_docling_progress_label",
    "_docling_progress_reporter",
    "_low_confidence_ocr_items",
    "_vision_layout_progress_reporter",
    "chunk_text",
    "download_file",
    "embed_chunks",
    "extract_text",
    "generate_metadata",
    "mark_processing",
    "activate_generation",
    "upsert_qdrant",
]


def extract_text(state: IngestState, deps: IngestDependencies) -> IngestState:
    payload = state["payload"]
    if payload.review_batch_id:
        approved_items = deps.backend.get_review_batch_parsed_items(
            review_batch_id=payload.review_batch_id
        )
        state["parsed_items"] = [parsed_item_from_dict(item) for item in approved_items]
    elif payload.image_review_batch_id:
        parsed_items, approved_sources, candidate_count = _image_review_resume_inputs(
            payload.image_review_batch_id,
            deps,
        )
        parsed = resume_pdf_image_review(
            parsed_items,
            approved_sources,
            doc_id=payload.doc_id,
            image_asset_store=deps.image_asset_writer,
            image_analyzer=deps.vision,
            candidate_count=candidate_count,
            image_progress_callback=_image_progress_reporter(deps, payload.job_id),
        )
        state["parser_provenance"] = parsed.provenance
        deps.backend.record_parser_provenance(
            job_id=payload.job_id, provenance=parsed.provenance
        )
        if parsed.assets:
            deps.backend.replace_document_image_assets(
                doc_id=payload.doc_id,
                job_id=payload.job_id,
                assets=[parsed_image_asset_to_dict(asset) for asset in parsed.assets],
            )
        state["parsed_items"] = parsed.items
    else:
        try:
            parsed_items = parse_document(
                state["file_bytes"],
                content_type=payload.content_type,
                file_path=payload.file_path,
                min_chars_per_page=deps.min_chars_per_page,
                ingestion_quality_preset=deps.ingestion_quality_preset,
                weak_page_threshold=deps.weak_page_threshold,
                full_doc_weak_page_ratio=deps.full_doc_weak_page_ratio,
                layered_docling_max_pages=deps.layered_docling_max_pages,
                layered_docling_max_page_ratio=deps.layered_docling_max_page_ratio,
                prefer_full_document_docling=deps.prefer_full_document_docling,
                layered_docling_batch_pages=deps.layered_docling_batch_pages,
                page_progress_callback=_page_progress_reporter(deps, payload.job_id),
                docling_progress_callback=_docling_progress_reporter(
                    deps, payload.job_id
                ),
                vision_layout_progress_callback=_vision_layout_progress_reporter(
                    deps, payload.job_id
                ),
                image_progress_callback=_image_progress_reporter(deps, payload.job_id),
                pdf_image_analysis_max_images=deps.pdf_image_analysis_max_images,
                pdf_image_analysis_max_full_page_fallbacks=deps.pdf_image_analysis_max_full_page_fallbacks,
                pdf_image_review_threshold=deps.pdf_image_review_threshold,
                scanned_visual_region_enabled=deps.scanned_visual_region_enabled,
                scanned_visual_min_area_ratio=deps.scanned_visual_min_area_ratio,
                scanned_visual_max_regions_per_page=deps.scanned_visual_max_regions_per_page,
                scanned_visual_text_mask_padding_px=deps.scanned_visual_text_mask_padding_px,
                vision_layout_repair_enabled=deps.vision_layout_repair_enabled,
                doc_id=payload.doc_id,
                image_asset_store=deps.image_asset_writer,
                image_analyzer=deps.vision,
            )
        except PdfImageReviewRequired as exc:
            provenance = _image_review_required_provenance(exc)
            state["parser_provenance"] = provenance
            deps.backend.record_parser_provenance(
                job_id=payload.job_id, provenance=provenance
            )
            if exc.parsed.assets:
                deps.backend.replace_document_image_assets(
                    doc_id=payload.doc_id,
                    job_id=payload.job_id,
                    assets=[
                        parsed_image_asset_to_dict(asset) for asset in exc.parsed.assets
                    ],
                )
            candidates = _image_review_candidates(exc, deps=deps, doc_id=payload.doc_id)
            image_review_batch_id = deps.backend.create_image_review_batch(
                job_id=payload.job_id,
                doc_id=payload.doc_id,
                parsed_items=[parsed_item_to_dict(item) for item in exc.parsed.items],
                resume_payload=payload.to_dict(),
                candidates=candidates,
            )
            deps.backend.update_job(
                job_id=payload.job_id,
                status="human_review",
                progress_pct=IMAGE_PROGRESS_START,
                stage_progress=_items_progress(
                    "images",
                    0,
                    len(candidates),
                    f"Image analysis needs review for {len(candidates)} candidates",
                ),
            )
            raise HumanReviewRequired(review_batch_id=image_review_batch_id)
        except Exception as exc:
            deps.backend.record_parser_provenance(
                job_id=payload.job_id,
                provenance=_parser_failure_provenance(
                    deps, payload.content_type, payload.file_path, exc
                ),
            )
            raise
        state["parser_provenance"] = parsed_items.provenance
        deps.backend.record_parser_provenance(
            job_id=payload.job_id, provenance=parsed_items.provenance
        )
        if parsed_items.assets:
            deps.backend.replace_document_image_assets(
                doc_id=payload.doc_id,
                job_id=payload.job_id,
                assets=[
                    parsed_image_asset_to_dict(asset) for asset in parsed_items.assets
                ],
            )
        parsed_items = parsed_items.items
        review_items = _low_confidence_ocr_items(
            parsed_items, deps.ocr_review_confidence_threshold
        )
        if review_items:
            review_batch_id = deps.backend.create_review_batch(
                job_id=payload.job_id,
                doc_id=payload.doc_id,
                parsed_items=[parsed_item_to_dict(item) for item in parsed_items],
                resume_payload=payload.to_dict(),
                review_items=review_items,
            )
            deps.backend.update_job(
                job_id=payload.job_id,
                status="human_review",
                progress_pct=PARSE_PROGRESS_COMPLETE,
                stage_progress=_items_progress(
                    "pages",
                    _page_count(parsed_items),
                    _page_count(parsed_items),
                    "Parsed pages need review",
                ),
            )
            raise HumanReviewRequired(review_batch_id=review_batch_id)
        state["parsed_items"] = parsed_items
    page_count = _page_count(state["parsed_items"])
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=PARSE_PROGRESS_COMPLETE,
        stage_progress=(
            _items_progress("pages", page_count, page_count, "Parsed all pages")
            if page_count
            else None
        ),
    )
    return state


def generate_metadata(state: IngestState, deps: IngestDependencies) -> IngestState:
    job_id = state["payload"].job_id
    model_label = _metadata_model_label(deps)
    deps.backend.update_job(
        job_id=job_id,
        status="processing",
        progress_pct=METADATA_PROGRESS_START,
        stage_progress=_items_progress(
            "metadata", 0, 1, f"Requesting metadata from {model_label}"
        ),
    )
    text = "\n\n".join(item.text for item in state["parsed_items"])
    with _metadata_progress_reporter(deps, job_id=job_id, model_label=model_label):
        llm_metadata = generate_metadata_v2(
            state["parsed_items"], deps.ollama.generate_metadata
        )
    warnings = [str(item) for item in llm_metadata.pop("_warnings", [])]
    metadata_errors = _metadata_errors(llm_metadata.pop("_metadata_errors", []))
    state["warnings"] = list(dict.fromkeys([*state.get("warnings", []), *warnings]))
    if warnings:
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=METADATA_PROGRESS_END,
            stage_progress=_items_progress(
                "metadata", 1, 1, "Using deterministic metadata fallback"
            ),
            warnings=state.get("warnings", []),
        )
    state["metadata"] = build_metadata_bundle(
        text=text,
        job=state["payload"],
        llm_metadata=llm_metadata,
        topic_taxonomy=deps.topic_taxonomy,
        use_gliner=deps.metadata_use_gliner,
    ).as_worker_metadata()
    if warnings:
        metadata_flags = state["metadata"].setdefault("metadata_flags", {})
        metadata_flags["metadata_generation_degraded"] = True
        metadata_flags["metadata_warnings"] = warnings
        if metadata_errors:
            metadata_flags["metadata_error"] = metadata_errors[0]
            metadata_flags["metadata_errors"] = metadata_errors
        if "ollama_metadata_unavailable" in warnings or any(
            warning.startswith("ollama_metadata_") for warning in warnings
        ):
            metadata_flags["ollama_metadata_unavailable"] = True
        deps.backend.record_event(
            job_id=state["payload"].job_id,
            event_type="degraded",
            payload={
                "warnings": warnings,
                "component": "metadata_generation",
                "metadata_errors": metadata_errors,
            },
        )
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=50,
        warnings=state.get("warnings", []),
    )
    return state


@contextmanager
def _metadata_progress_reporter(
    deps: IngestDependencies,
    *,
    job_id: str,
    model_label: str,
) -> Iterator[None]:
    stopped = threading.Event()
    started = time.monotonic()
    tick_count = 0

    def report() -> None:
        nonlocal tick_count
        while not stopped.wait(METADATA_PROGRESS_INTERVAL_SECONDS):
            try:
                _raise_if_job_cancelled(deps, job_id)
            except IngestJobCancelled:
                return
            except Exception:
                pass
            tick_count += 1
            elapsed = max(1, int(time.monotonic() - started))
            try:
                deps.backend.update_job(
                    job_id=job_id,
                    status="processing",
                    progress_pct=min(
                        METADATA_PROGRESS_END, METADATA_PROGRESS_START + tick_count
                    ),
                    stage_progress=_items_progress(
                        "metadata",
                        min(
                            tick_count, METADATA_PROGRESS_END - METADATA_PROGRESS_START
                        ),
                        METADATA_PROGRESS_END - METADATA_PROGRESS_START,
                        f"Waiting on {model_label} for {_duration_label(elapsed)}",
                    ),
                )
            except Exception:
                continue

    thread = threading.Thread(
        target=report, name=f"metadata-progress-{job_id}", daemon=True
    )
    thread.start()
    try:
        yield
    finally:
        stopped.set()
    thread.join(timeout=1)


def _metadata_model_label(deps: IngestDependencies) -> str:
    model = str(getattr(deps.ollama, "chat_model", "") or "").strip()
    class_name = type(deps.ollama).__name__.lower()
    if "ollama" in class_name:
        prefix = "Ollama metadata model"
    elif "openai" in class_name:
        prefix = "OpenAI-compatible metadata model"
    else:
        prefix = "metadata model"
    return f"{prefix} {model}" if model else prefix


def _metadata_errors(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)][:5]


def _low_confidence_ocr_items(
    items: list[ParsedPdfItem], threshold: float
) -> list[dict[str, object]]:
    review_items: list[dict[str, object]] = []
    for item in items:
        if "source:ocr" not in item.quality_flags:
            continue
        if item.confidence is not None and item.confidence >= threshold:
            continue
        if not item.text.strip():
            continue
        review_items.append(
            {
                "item_index": item.index,
                "item_type": item.item_type,
                "page_start": item.page_start,
                "page_end": item.page_end,
                "bbox": list(item.bbox) if item.bbox is not None else None,
                "quality_flags": list(item.quality_flags),
                "partial_text": item.text,
                "confidence": item.confidence,
            }
        )
    return review_items
