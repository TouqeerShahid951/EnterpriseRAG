"""Side-effecting nodes for the native PDF ingestion graph."""

from __future__ import annotations

from ..chunking import chunk_items
from ..errors import HumanReviewRequired
from ..indexing.claims import build_claim_records
from ..indexing.metadata_text import build_embedding_texts
from ..indexing.payloads import build_qdrant_points
from ..metadata import build_metadata_bundle, generate_metadata_v2
from ..parsers import parse_document
from ..parsers.models import ParsedPdfItem, parsed_image_asset_to_dict, parsed_item_from_dict, parsed_item_to_dict
from .state import IngestDependencies, IngestState


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
                weak_page_threshold=deps.weak_page_threshold,
                full_doc_weak_page_ratio=deps.full_doc_weak_page_ratio,
                layered_docling_max_pages=deps.layered_docling_max_pages,
                layered_docling_batch_pages=deps.layered_docling_batch_pages,
                page_progress_callback=_page_progress_reporter(deps, payload.job_id),
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
                progress_pct=35,
                stage_progress=_items_progress("pages", _page_count(parsed_items), _page_count(parsed_items), "Parsed pages need review"),
            )
            raise HumanReviewRequired(review_batch_id=review_batch_id)
        state["parsed_items"] = parsed_items
    page_count = _page_count(state["parsed_items"])
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=35,
        stage_progress=_items_progress("pages", page_count, page_count, "Parsed all pages") if page_count else None,
    )
    return state


def generate_metadata(state: IngestState, deps: IngestDependencies) -> IngestState:
    text = "\n\n".join(item.text for item in state["parsed_items"])
    llm_metadata = generate_metadata_v2(state["parsed_items"], deps.ollama.generate_metadata)
    warnings = [str(item) for item in llm_metadata.pop("_warnings", [])]
    state["warnings"] = list(dict.fromkeys([*state.get("warnings", []), *warnings]))
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
        if "ollama_metadata_unavailable" in warnings:
            metadata_flags["ollama_metadata_unavailable"] = True
        deps.backend.record_event(
            job_id=state["payload"].job_id,
            event_type="degraded",
            payload={"warnings": warnings, "component": "metadata_generation"},
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
        if not _should_report_progress(page_no, page_count, last_reported=last_reported):
            return
        last_reported = page_no
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=_bounded_progress(20, 34, page_no, page_count),
            stage_progress=_items_progress("pages", page_no, page_count, f"Parsing page {page_no} of {page_count}"),
        )

    return report


def _items_progress(unit: str, current: int, total: int, label: str) -> dict[str, object]:
    return {"unit": unit, "current": max(0, current), "total": max(0, total), "label": label}


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


def _parser_failure_provenance(deps: IngestDependencies, content_type: str | None, file_path: str, exc: Exception) -> dict[str, object]:
    return {
        "version": 1,
        "document_kind": _document_kind(content_type, file_path),
        "page_count": None,
        "primary_parser": "layered",
        "secondary_parser": "docling",
        "routing_mode": "parse_failed",
        "config": {
            "min_chars_per_page": deps.min_chars_per_page,
            "weak_page_threshold": deps.weak_page_threshold,
            "full_doc_weak_page_ratio": deps.full_doc_weak_page_ratio,
            "layered_docling_max_pages": deps.layered_docling_max_pages,
            "layered_docling_batch_pages": deps.layered_docling_batch_pages,
        },
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
