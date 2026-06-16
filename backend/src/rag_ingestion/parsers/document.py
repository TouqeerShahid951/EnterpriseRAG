"""Generic document parser dispatch for upload ingestion."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from ..errors import UnsupportedDocumentError, UnsupportedPdfError, WorkerStepError
from .docling_adapter import parse_docling_docx, parse_docling_pdf
from .hierarchy import apply_hierarchy
from .images import ImageAnalyzer, ImageAssetStore, docx_image_sources, image_sources_to_items, parse_image_document, pdf_image_sources
from .models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from .pdf import parse_pdf_document
from .provenance import base_report, parser_item_counts, parser_page_counts, quality_flag_counts

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
PageProgressCallback = Callable[[int, int], None]


def parse_document(
    file_bytes: bytes,
    *,
    content_type: str | None,
    file_path: str,
    min_chars_per_page: int,
    weak_page_threshold: int = 5,
    full_doc_weak_page_ratio: float = 0.25,
    layered_docling_max_pages: int = 40,
    layered_docling_batch_pages: int = 4,
    page_progress_callback: PageProgressCallback | None = None,
    doc_id: str | None = None,
    image_asset_store: ImageAssetStore | None = None,
    image_analyzer: ImageAnalyzer | None = None,
) -> DocumentParseResult:
    kind = _document_kind(content_type, file_path)
    image_context = _image_context(doc_id, image_asset_store, image_analyzer)
    if kind == "pdf":
        parsed = _parse_pdf_with_ocr_fallback(
            file_bytes,
            min_chars_per_page=min_chars_per_page,
            weak_page_threshold=weak_page_threshold,
            full_doc_weak_page_ratio=full_doc_weak_page_ratio,
            layered_docling_max_pages=layered_docling_max_pages,
            layered_docling_batch_pages=layered_docling_batch_pages,
            page_progress_callback=page_progress_callback,
        )
        if image_context is None:
            return parsed
        image_items, image_assets = image_sources_to_items(
            pdf_image_sources(file_bytes),
            doc_id=image_context[0],
            store=image_context[1],
            analyzer=image_context[2],
            start_index=len(parsed.items),
        )
        return _append_image_outputs(parsed, image_items=image_items, image_assets=image_assets)
    if kind == "docx":
        items = _validated_docx_items(file_bytes)
        image_assets = []
        if image_context is not None:
            image_items, image_assets = image_sources_to_items(
                docx_image_sources(file_bytes),
                doc_id=image_context[0],
                store=image_context[1],
                analyzer=image_context[2],
                start_index=len(items),
            )
            items = _renumber_items([*items, *image_items])
        return DocumentParseResult(
            items=items,
            provenance=base_report(
                document_kind="docx",
                page_count=None,
                primary_parser="docling",
                secondary_parser="vision" if image_context is not None else None,
                routing_mode="docling_docx",
                config={},
                items=items,
            ) | {"image_asset_count": len(image_assets)},
            assets=image_assets,
        )
    if kind == "image":
        if image_context is None:
            raise WorkerStepError("image_processing_unavailable", "Image processing dependencies are not configured.")
        return parse_image_document(
            file_bytes,
            doc_id=image_context[0],
            store=image_context[1],
            analyzer=image_context[2],
            content_type=content_type,
            filename=file_path.rsplit("/", 1)[-1] or "upload",
        )
    raise UnsupportedDocumentError()


def _parse_pdf_with_ocr_fallback(
    file_bytes: bytes,
    *,
    min_chars_per_page: int,
    weak_page_threshold: int,
    full_doc_weak_page_ratio: float,
    layered_docling_max_pages: int,
    layered_docling_batch_pages: int,
    page_progress_callback: PageProgressCallback | None = None,
) -> DocumentParseResult:
    try:
        return parse_pdf_document(
            file_bytes,
            min_chars_per_page=min_chars_per_page,
            weak_page_threshold=weak_page_threshold,
            full_doc_weak_page_ratio=full_doc_weak_page_ratio,
            layered_docling_max_pages=layered_docling_max_pages,
            layered_docling_batch_pages=layered_docling_batch_pages,
            page_progress_callback=page_progress_callback,
        )
    except UnsupportedPdfError:
        try:
            items = parse_docling_pdf(file_bytes, allow_page_repair=True, mark_ocr=True)
        except ImportError as exc:
            raise WorkerStepError("ocr_dependency_missing", "Docling OCR dependency is not installed.") from exc
        if not items:
            raise
        items = apply_hierarchy(_renumber_items(items))
        return DocumentParseResult(
            items=items,
            provenance=base_report(
                document_kind="pdf",
                page_count=_page_count(items),
                primary_parser="layered",
                secondary_parser="docling",
                routing_mode="ocr_fallback",
                config={
                    "min_chars_per_page": min_chars_per_page,
                    "weak_page_threshold": weak_page_threshold,
                    "full_doc_weak_page_ratio": full_doc_weak_page_ratio,
                    "layered_docling_max_pages": layered_docling_max_pages,
                    "layered_docling_batch_pages": layered_docling_batch_pages,
                },
                items=items,
                fallback={"from": "layered", "to": "docling", "reason": "native_text_unsupported"},
            ),
        )


def _validated_docx_items(file_bytes: bytes) -> list[ParsedPdfItem]:
    try:
        items = parse_docling_docx(file_bytes)
    except ImportError as exc:
        raise WorkerStepError("docx_dependency_missing", "Docling DOCX dependency is not installed.") from exc
    except Exception as exc:
        raise WorkerStepError("docx_parse_failed", "Docling failed to parse DOCX.") from exc
    if not items or not "".join(item.text for item in items).strip():
        raise UnsupportedDocumentError()
    return apply_hierarchy(_renumber_items(items))


def _document_kind(content_type: str | None, file_path: str) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized == PDF_CONTENT_TYPE:
        return "pdf"
    if normalized == DOCX_CONTENT_TYPE:
        return "docx"
    if normalized in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
        return "image"
    lowered_path = file_path.lower()
    if lowered_path.endswith((".jpg", ".jpeg", ".png")):
        return "image"
    if lowered_path.endswith(".docx"):
        return "docx"
    return "pdf" if lowered_path.endswith(".pdf") or not normalized else "unsupported"


def _page_count(items: list[ParsedPdfItem]) -> int:
    pages = [
        page
        for item in items
        for page in (item.page_start, item.page_end)
        if isinstance(page, int) and page > 0
    ]
    return max(pages) if pages else 0


def _renumber_items(items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    return [replace(item, index=index) for index, item in enumerate(items)]


def _image_context(
    doc_id: str | None,
    image_asset_store: ImageAssetStore | None,
    image_analyzer: ImageAnalyzer | None,
) -> tuple[str, ImageAssetStore, ImageAnalyzer] | None:
    if doc_id is None or image_asset_store is None or image_analyzer is None:
        return None
    return doc_id, image_asset_store, image_analyzer


def _append_image_outputs(
    parsed: DocumentParseResult,
    *,
    image_items: list[ParsedPdfItem],
    image_assets: list[ParsedImageAsset],
) -> DocumentParseResult:
    if not image_items and not image_assets:
        return parsed
    items = _renumber_items([*parsed.items, *image_items])
    provenance = {
        **parsed.provenance,
        "secondary_parser": "vision",
        "parser_item_counts": parser_item_counts(items),
        "parser_page_counts": parser_page_counts(items),
        "quality_flag_counts": quality_flag_counts(items),
        "image_asset_count": len(image_assets),
    }
    return DocumentParseResult(items=items, provenance=provenance, assets=list(image_assets))
