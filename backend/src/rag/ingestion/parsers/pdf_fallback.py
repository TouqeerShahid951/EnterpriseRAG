"""Layered PDF parsing and its OCR/vision fallback policies."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from ..errors import UnsupportedPdfError, WorkerStepError
from .docling_adapter import DoclingProgressCallback, parse_docling_pdf
from .hierarchy import apply_hierarchy
from .images import (
    ImageAnalyzer,
    ImageAssetStore,
    ImageProgressCallback,
    ImageSource,
    image_sources_to_items,
    pdf_image_sources,
)
from .models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from .pdf import PageProgressCallback, parse_pdf_document
from .pdf_image_processing import page_count, renumber_items
from .provenance import base_report


def parse_pdf_with_ocr_fallback(
    file_bytes: bytes,
    *,
    min_chars_per_page: int,
    ingestion_quality_preset: str,
    weak_page_threshold: int,
    full_doc_weak_page_ratio: float,
    layered_docling_max_pages: int,
    layered_docling_max_page_ratio: float | None,
    prefer_full_document_docling: bool,
    layered_docling_batch_pages: int,
    page_progress_callback: PageProgressCallback | None = None,
    docling_progress_callback: DoclingProgressCallback | None = None,
) -> DocumentParseResult:
    try:
        return parse_pdf_document(
            file_bytes,
            min_chars_per_page=min_chars_per_page,
            quality_preset=ingestion_quality_preset,
            weak_page_threshold=weak_page_threshold,
            full_doc_weak_page_ratio=full_doc_weak_page_ratio,
            layered_docling_max_pages=layered_docling_max_pages,
            layered_docling_max_page_ratio=layered_docling_max_page_ratio,
            prefer_full_document_docling=prefer_full_document_docling,
            layered_docling_batch_pages=layered_docling_batch_pages,
            page_progress_callback=page_progress_callback,
            docling_progress_callback=docling_progress_callback,
        )
    except UnsupportedPdfError:
        try:
            items = parse_docling_pdf(
                file_bytes,
                allow_page_repair=True,
                mark_ocr=True,
                progress_callback=docling_progress_callback,
                progress_phase="ocr_fallback",
            )
        except ImportError as exc:
            raise WorkerStepError(
                "ocr_dependency_missing", "Docling OCR dependency is not installed."
            ) from exc
        if not items:
            raise
        items = apply_hierarchy(renumber_items(items))
        return DocumentParseResult(
            items=items,
            provenance=base_report(
                document_kind="pdf",
                page_count=page_count(items),
                primary_parser="layered",
                secondary_parser="docling",
                routing_mode="ocr_fallback",
                config=pdf_parser_config(
                    min_chars_per_page=min_chars_per_page,
                    ingestion_quality_preset=ingestion_quality_preset,
                    weak_page_threshold=weak_page_threshold,
                    full_doc_weak_page_ratio=full_doc_weak_page_ratio,
                    layered_docling_max_pages=layered_docling_max_pages,
                    layered_docling_max_page_ratio=layered_docling_max_page_ratio,
                    prefer_full_document_docling=prefer_full_document_docling,
                    layered_docling_batch_pages=layered_docling_batch_pages,
                ),
                items=items,
                fallback={
                    "from": "layered",
                    "to": "docling",
                    "reason": "native_text_unsupported",
                },
            ),
        )


def parse_pdf_with_vision_fallback(
    file_bytes: bytes,
    *,
    image_context: tuple[str, ImageAssetStore, ImageAnalyzer] | None,
    parser_config: dict[str, object],
    parse_error: Exception,
    image_progress_callback: ImageProgressCallback | None = None,
    image_source_factory: Callable[[bytes], list[ImageSource]] = pdf_image_sources,
    items_factory: Callable[
        ..., tuple[list[ParsedPdfItem], list[ParsedImageAsset]]
    ] = image_sources_to_items,
) -> DocumentParseResult | None:
    if image_context is None:
        return None
    try:
        image_items, image_assets = items_factory(
            image_source_factory(file_bytes),
            doc_id=image_context[0],
            store=image_context[1],
            analyzer=image_context[2],
            start_index=0,
            progress_callback=image_progress_callback,
        )
    except Exception:
        return None
    if not image_items:
        return None
    items = renumber_items(vision_fallback_items(image_items, parse_error=parse_error))
    return DocumentParseResult(
        items=items,
        provenance=base_report(
            document_kind="pdf",
            page_count=page_count(items),
            primary_parser="vision",
            secondary_parser=None,
            routing_mode="vision_fallback",
            config=parser_config,
            items=items,
            fallback={
                "from": "layered_docling_ocr",
                "to": "vision",
                "reason": parse_error_code(parse_error),
            },
            errors=[{"component": "parser", "code": parse_error_code(parse_error)}],
        )
        | {"image_asset_count": len(image_assets)},
        assets=image_assets,
    )


def pdf_parser_config(
    *,
    min_chars_per_page: int,
    ingestion_quality_preset: str,
    weak_page_threshold: int,
    full_doc_weak_page_ratio: float,
    layered_docling_max_pages: int,
    layered_docling_max_page_ratio: float | None,
    prefer_full_document_docling: bool,
    layered_docling_batch_pages: int,
) -> dict[str, object]:
    return {
        "min_chars_per_page": min_chars_per_page,
        "quality_preset": ingestion_quality_preset,
        "weak_page_threshold": weak_page_threshold,
        "full_doc_weak_page_ratio": full_doc_weak_page_ratio,
        "layered_docling_max_pages": layered_docling_max_pages,
        "layered_docling_max_page_ratio": layered_docling_max_page_ratio,
        "prefer_full_document_docling": prefer_full_document_docling,
        "layered_docling_batch_pages": layered_docling_batch_pages,
    }


def vision_fallback_items(
    items: list[ParsedPdfItem], *, parse_error: Exception
) -> list[ParsedPdfItem]:
    flags = {"vision_pdf_page_fallback", parse_error_quality_flag(parse_error)}
    return [
        replace(item, quality_flags=sorted({*item.quality_flags, *flags}))
        for item in items
    ]


def parse_error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return str(code) if code else type(exc).__name__


def parse_error_quality_flag(exc: Exception) -> str:
    code = parse_error_code(exc)
    if code == "ocr_dependency_missing":
        return "docling_ocr_unavailable"
    if code == "unsupported_pdf_type":
        return "docling_ocr_empty"
    return "docling_ocr_failed"
