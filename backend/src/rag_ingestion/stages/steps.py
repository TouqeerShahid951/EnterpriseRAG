"""Side-effecting nodes for the native PDF ingestion graph."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import threading
import time

from ..chunking import chunk_items
from ..errors import HumanReviewRequired, IngestJobCancelled
from ..indexing.claims import build_claim_records
from ..indexing.metadata_text import build_embedding_texts
from ..indexing.payloads import build_qdrant_points
from ..metadata import build_metadata_bundle, generate_metadata_v2
from ..parsers import parse_document
from ..parsers.models import ParsedPdfItem, parsed_image_asset_to_dict, parsed_item_from_dict, parsed_item_to_dict
from .state import IngestDependencies, IngestState

METADATA_PROGRESS_INTERVAL_SECONDS = 15.0
PARSE_PROGRESS_COMPLETE = 36
IMAGE_PROGRESS_START = 35
IMAGE_PROGRESS_END = 36
METADATA_PROGRESS_START = 37
METADATA_PROGRESS_END = 49


def mark_processing(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.backend.update_job(job_id=state["payload"].job_id, status="processing", progress_pct=5)
    return state


def download_file(state: IngestState, deps: IngestDependencies) -> IngestState:
    state["file_bytes"] = deps.storage.read(state["payload"].file_path)
    deps.backend.update_job(job_id=state["payload"].job_id, status="processing", progress_pct=20)
    return state


def extract_text(state: IngestState, deps: IngestDependencies) -> IngestState:
    payload = state["payload"]
    if payload.review_batch_id:
        approved_items = deps.backend.get_review_batch_parsed_items(review_batch_id=payload.review_batch_id)
        state["parsed_items"] = [parsed_item_from_dict(item) for item in approved_items]
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
                docling_progress_callback=_docling_progress_reporter(deps, payload.job_id),
                vision_layout_progress_callback=_vision_layout_progress_reporter(deps, payload.job_id),
                image_progress_callback=_image_progress_reporter(deps, payload.job_id),
                pdf_image_analysis_max_images=deps.pdf_image_analysis_max_images,
                pdf_image_analysis_max_full_page_fallbacks=deps.pdf_image_analysis_max_full_page_fallbacks,
                scanned_visual_region_enabled=deps.scanned_visual_region_enabled,
                scanned_visual_min_area_ratio=deps.scanned_visual_min_area_ratio,
                scanned_visual_max_regions_per_page=deps.scanned_visual_max_regions_per_page,
                scanned_visual_text_mask_padding_px=deps.scanned_visual_text_mask_padding_px,
                vision_layout_repair_enabled=deps.vision_layout_repair_enabled,
                doc_id=payload.doc_id,
                image_asset_store=deps.image_asset_writer,
                image_analyzer=deps.vision,
            )
        except Exception as exc:
            deps.backend.record_parser_provenance(
                job_id=payload.job_id,
                provenance=_parser_failure_provenance(deps, payload.content_type, payload.file_path, exc),
            )
            raise
        state["parser_provenance"] = parsed_items.provenance
        deps.backend.record_parser_provenance(job_id=payload.job_id, provenance=parsed_items.provenance)
        if parsed_items.assets:
            deps.backend.replace_document_image_assets(
                doc_id=payload.doc_id,
                job_id=payload.job_id,
                assets=[parsed_image_asset_to_dict(asset) for asset in parsed_items.assets],
            )
        parsed_items = parsed_items.items
        review_items = _low_confidence_ocr_items(parsed_items, deps.ocr_review_confidence_threshold)
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
                stage_progress=_items_progress("pages", _page_count(parsed_items), _page_count(parsed_items), "Parsed pages need review"),
            )
            raise HumanReviewRequired(review_batch_id=review_batch_id)
        state["parsed_items"] = parsed_items
    page_count = _page_count(state["parsed_items"])
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=PARSE_PROGRESS_COMPLETE,
        stage_progress=_items_progress("pages", page_count, page_count, "Parsed all pages") if page_count else None,
    )
    return state


def generate_metadata(state: IngestState, deps: IngestDependencies) -> IngestState:
    job_id = state["payload"].job_id
    model_label = _metadata_model_label(deps)
    deps.backend.update_job(
        job_id=job_id,
        status="processing",
        progress_pct=METADATA_PROGRESS_START,
        stage_progress=_items_progress("metadata", 0, 1, f"Requesting metadata from {model_label}"),
    )
    text = "\n\n".join(item.text for item in state["parsed_items"])
    with _metadata_progress_reporter(deps, job_id=job_id, model_label=model_label):
        llm_metadata = generate_metadata_v2(state["parsed_items"], deps.ollama.generate_metadata)
    warnings = [str(item) for item in llm_metadata.pop("_warnings", [])]
    metadata_errors = _metadata_errors(llm_metadata.pop("_metadata_errors", []))
    state["warnings"] = list(dict.fromkeys([*state.get("warnings", []), *warnings]))
    if warnings:
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=METADATA_PROGRESS_END,
            stage_progress=_items_progress("metadata", 1, 1, "Using deterministic metadata fallback"),
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
        if "ollama_metadata_unavailable" in warnings or any(warning.startswith("ollama_metadata_") for warning in warnings):
            metadata_flags["ollama_metadata_unavailable"] = True
        deps.backend.record_event(
            job_id=state["payload"].job_id,
            event_type="degraded",
            payload={"warnings": warnings, "component": "metadata_generation", "metadata_errors": metadata_errors},
        )
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=50,
        warnings=state.get("warnings", []),
    )
    return state


def persist_document_metadata(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.backend.save_document_metadata(doc_id=state["payload"].doc_id, metadata=state["metadata"])
    deps.backend.update_job(job_id=state["payload"].job_id, status="processing", progress_pct=55)
    return state


def chunk_text(state: IngestState, deps: IngestDependencies) -> IngestState:
    state["chunks"] = chunk_items(
        state["parsed_items"],
        doc_id=state["payload"].doc_id,
        target_tokens=deps.chunk_target_tokens,
        overlap_tokens=deps.chunk_overlap_tokens,
        parent_max_tokens=deps.parent_max_tokens,
    )
    if not state["chunks"]:
        raise RuntimeError("document extraction produced no chunks")
    state["claims"] = build_claim_records(
        job=state["payload"],
        chunks=state["chunks"],
        metadata=state["metadata"],
    )
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=60,
        stage_progress=_items_progress("chunks", len(state["chunks"]), len(state["chunks"]), "Built retrieval chunks"),
    )
    return state


def persist_claims(state: IngestState, deps: IngestDependencies) -> IngestState:
    state["conflicted_claim_ids"] = deps.backend.save_ingest_claims(
        doc_id=state["payload"].doc_id,
        claims=state["claims"],
    )
    deps.backend.update_job(job_id=state["payload"].job_id, status="processing", progress_pct=65)
    return state


def embed_chunks(state: IngestState, deps: IngestDependencies) -> IngestState:
    chunks = state["chunks"]
    embedding_texts = build_embedding_texts(
        file_path=state["payload"].file_path,
        chunks=chunks,
        metadata=state["metadata"],
    )
    def report(index: int, total: int) -> None:
        _raise_if_job_cancelled(deps, state["payload"].job_id)
        if _should_report_progress(index, len(chunks)):
            deps.backend.update_job(
                job_id=state["payload"].job_id,
                status="processing",
                progress_pct=_bounded_progress(65, 74, index, len(chunks)),
                stage_progress=_items_progress("chunks", index, len(chunks), f"Embedding chunk {index} of {len(chunks)}"),
            )

    state["vectors"] = deps.ollama.embed_many(embedding_texts, progress=report)
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=75,
        stage_progress=_items_progress("vectors", len(chunks), len(chunks), "Generating sparse vectors"),
    )
    state["sparse_vectors"] = deps.sparse_embedder.embed_many(embedding_texts)
    state["points"] = build_qdrant_points(
        job=state["payload"],
        chunks=state["chunks"],
        vectors=state["vectors"],
        sparse_vectors=state["sparse_vectors"],
        metadata=state["metadata"],
        file_bytes=state["file_bytes"],
        claims=state["claims"],
        conflicted_claim_ids=state.get("conflicted_claim_ids", []),
    )
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=78,
        stage_progress=_items_progress("vectors", len(state["points"]), len(state["points"]), "Prepared vectors for indexing"),
    )
    return state


def upsert_qdrant(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.qdrant.ensure_collection(len(state["vectors"][0]))
    _raise_if_job_cancelled(deps, state["payload"].job_id)
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=82,
        stage_progress=_items_progress("vectors", 0, len(state["points"]), "Writing vectors to Qdrant"),
    )
    state["upsert_count"] = deps.qdrant.replace_document(doc_id=state["payload"].doc_id, points=state["points"])
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=92,
        stage_progress=_items_progress("vectors", state["upsert_count"], len(state["points"]), "Indexed vectors"),
    )
    return state


def commit_supersession(state: IngestState, deps: IngestDependencies) -> IngestState:
    if state["payload"].supersedes:
        deps.qdrant.mark_documents_not_current(state["payload"].supersedes)
        deps.backend.commit_supersession(new_doc_id=state["payload"].doc_id, supersedes=state["payload"].supersedes)
    return state


def mark_complete(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="complete",
        progress_pct=100,
        warnings=state.get("warnings", []),
    )
    return state


def _page_progress_reporter(deps: IngestDependencies, job_id: str):
    last_reported = 0

    def report(page_no: int, page_count: int) -> None:
        nonlocal last_reported
        _raise_if_job_cancelled(deps, job_id)
        if not _should_report_progress(page_no, page_count, last_reported=last_reported):
            return
        last_reported = page_no
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=_bounded_progress(20, 30, page_no, page_count),
            stage_progress=_items_progress("pages", page_no, page_count, f"Parsing page {page_no} of {page_count}"),
        )

    return report


def _docling_progress_reporter(deps: IngestDependencies, job_id: str):
    def report(event: dict[str, object]) -> None:
        _raise_if_job_cancelled(deps, job_id)
        current = _int_value(event.get("current"))
        total = max(1, _int_value(event.get("total")))
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=_bounded_progress(30, 34, current, total),
            stage_progress=_items_progress("pages", current, total, _docling_progress_label(event)),
        )

    return report


def _vision_layout_progress_reporter(deps: IngestDependencies, job_id: str):
    def report(event: dict[str, object]) -> None:
        _raise_if_job_cancelled(deps, job_id)
        current = _int_value(event.get("current"))
        total = max(1, _int_value(event.get("total")))
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=_bounded_progress(34, 35, current, total),
            stage_progress=_items_progress("pages", current, total, _vision_layout_progress_label(event)),
        )

    return report


def _image_progress_reporter(deps: IngestDependencies, job_id: str):
    def report(event: dict[str, object]) -> None:
        _raise_if_job_cancelled(deps, job_id)
        current = _int_value(event.get("current"))
        total = max(1, _int_value(event.get("total")))
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=_bounded_progress(IMAGE_PROGRESS_START, IMAGE_PROGRESS_END, current, total),
            stage_progress=_items_progress("images", current, total, _image_progress_label(event)),
        )

    return report


def _items_progress(unit: str, current: int, total: int, label: str) -> dict[str, object]:
    return {"unit": unit, "current": max(0, current), "total": max(0, total), "label": label}


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
                    progress_pct=min(METADATA_PROGRESS_END, METADATA_PROGRESS_START + tick_count),
                    stage_progress=_items_progress(
                        "metadata",
                        min(tick_count, METADATA_PROGRESS_END - METADATA_PROGRESS_START),
                        METADATA_PROGRESS_END - METADATA_PROGRESS_START,
                        f"Waiting on {model_label} for {_duration_label(elapsed)}",
                    ),
                )
            except Exception:
                continue

    thread = threading.Thread(target=report, name=f"metadata-progress-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
    thread.join(timeout=1)


def _raise_if_job_cancelled(deps: IngestDependencies, job_id: str) -> None:
    get_status = getattr(deps.backend, "get_job_status", None)
    if not callable(get_status):
        return
    if get_status(job_id=job_id).status == "cancelled":
        raise IngestJobCancelled(job_id=job_id)


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


def _duration_label(total_seconds: int) -> str:
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}m {seconds}s" if seconds else f"{minutes}m"


def _should_report_progress(current: int, total: int, *, last_reported: int = 0) -> bool:
    return current <= 1 or current >= total or current - last_reported >= 5


def _bounded_progress(start: int, end: int, current: int, total: int) -> int:
    if total <= 0:
        return start
    span = max(0, end - start)
    return max(start, min(end, start + int(span * (current / total))))


def _page_count(items: list[ParsedPdfItem]) -> int:
    pages = [
        page
        for item in items
        for page in (item.page_start, item.page_end)
        if isinstance(page, int) and page > 0
    ]
    return max(pages) if pages else 0


def _docling_progress_label(event: dict[str, object]) -> str:
    phase = str(event.get("phase") or "docling")
    status = str(event.get("status") or "running")
    current = _int_value(event.get("current"))
    total = max(1, _int_value(event.get("total")))
    pages = _int_tuple(event.get("pages"))
    page_count = len(pages) if pages else 1
    if status == "complete":
        selected_end = max(1, min(total, current))
        selected_start = max(1, selected_end - page_count + 1)
    else:
        selected_start = max(1, min(total, current + 1))
        selected_end = max(selected_start, min(total, current + page_count))
    selected_label = (
        f"selected page {selected_start}"
        if selected_start == selected_end
        else f"selected pages {selected_start}-{selected_end}"
    )
    page_label = _pdf_page_label(pages)
    action = _docling_action(phase=phase, status=status)
    return f"{action} {selected_label} of {total} ({page_label})"


def _docling_action(*, phase: str, status: str) -> str:
    complete = status == "complete"
    if phase == "ocr_repair":
        return "Docling OCR repaired" if complete else "Docling OCR repairing"
    if phase == "page_repair":
        return "Docling repaired" if complete else "Docling repairing"
    if phase == "ocr_fallback":
        return "Docling OCR fallback parsed" if complete else "Docling OCR fallback parsing"
    if phase == "layout":
        return "Docling analyzed" if complete else "Docling analyzing"
    return "Docling processed" if complete else "Docling processing"


def _vision_layout_progress_label(event: dict[str, object]) -> str:
    status = str(event.get("status") or "running")
    current = _int_value(event.get("current"))
    total = max(1, _int_value(event.get("total")))
    page_no = _int_value(event.get("page"))
    page_label = f"PDF page {page_no}" if page_no else "PDF page"
    if status == "complete":
        return f"Vision layout repaired page {current} of {total} ({page_label})"
    if status == "skipped":
        reason = str(event.get("reason") or "not used")
        return f"Vision layout skipped page {current} of {total} ({page_label}: {reason})"
    if status == "failed":
        return f"Vision layout failed page {current} of {total} ({page_label})"
    return f"Vision layout repairing page {current + 1} of {total} ({page_label})"


def _image_progress_label(event: dict[str, object]) -> str:
    status = str(event.get("status") or "running")
    current = _int_value(event.get("current"))
    total = max(1, _int_value(event.get("total")))
    page_no = _int_value(event.get("page"))
    source_kind = str(event.get("source_kind") or "image")
    image_label = _image_source_label(source_kind)
    page_label = f" (PDF page {page_no})" if page_no else ""
    if status == "complete":
        return f"Image analysis completed {image_label} {current} of {total}{page_label}"
    return f"Image analysis analyzing {image_label} {min(current + 1, total)} of {total}{page_label}"


def _image_source_label(source_kind: str) -> str:
    if source_kind == "pdf_page_image":
        return "page image"
    if source_kind == "pdf_page_layout":
        return "layout image"
    if source_kind == "pdf_image":
        return "embedded image"
    if source_kind == "docx_media":
        return "document image"
    return "image"


def _pdf_page_label(pages: tuple[int, ...]) -> str:
    if not pages:
        return "whole document"
    ranges: list[str] = []
    start = pages[0]
    previous = pages[0]
    for page_no in pages[1:]:
        if page_no == previous + 1:
            previous = page_no
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page_no
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    prefix = "PDF page" if len(pages) == 1 else "PDF pages"
    return f"{prefix} {', '.join(ranges)}"


def _int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    values: list[int] = []
    for item in value:
        if isinstance(item, int):
            values.append(item)
    return tuple(sorted(values))


def _int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def _parser_failure_provenance(deps: IngestDependencies, content_type: str | None, file_path: str, exc: Exception) -> dict[str, object]:
    document_kind = "json" if getattr(exc, "code", None) == "json_parse_failed" else _document_kind(content_type, file_path)
    parser_config: dict[str, object] = {} if document_kind == "json" else {
        "min_chars_per_page": deps.min_chars_per_page,
        "quality_preset": deps.ingestion_quality_preset,
        "weak_page_threshold": deps.weak_page_threshold,
        "full_doc_weak_page_ratio": deps.full_doc_weak_page_ratio,
        "layered_docling_max_pages": deps.layered_docling_max_pages,
        "layered_docling_max_page_ratio": deps.layered_docling_max_page_ratio,
        "prefer_full_document_docling": deps.prefer_full_document_docling,
        "layered_docling_batch_pages": deps.layered_docling_batch_pages,
    }
    return {
        "version": 1,
        "document_kind": document_kind,
        "page_count": None,
        "primary_parser": "json" if document_kind == "json" else "layered",
        "secondary_parser": None if document_kind == "json" else "docling",
        "routing_mode": "parse_failed",
        "config": parser_config,
        "docling_selection": None,
        "parser_item_counts": {},
        "parser_page_counts": {},
        "quality_flag_counts": {},
        "fallback": None,
        "errors": [{"component": "parser", "code": type(exc).__name__}],
    }


def _document_kind(content_type: str | None, file_path: str) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or file_path.lower().endswith(".docx"):
        return "docx"
    if normalized in {"image/jpeg", "image/png"} or file_path.lower().endswith((".jpg", ".jpeg", ".png")):
        return "image"
    if normalized == "application/json" or file_path.lower().endswith(".json"):
        return "json"
    if normalized and normalized != "application/pdf" and not file_path.lower().endswith(".pdf"):
        return "unsupported"
    return "pdf"


def _low_confidence_ocr_items(items: list[ParsedPdfItem], threshold: float) -> list[dict[str, object]]:
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
