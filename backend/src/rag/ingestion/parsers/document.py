"""Compatibility facade for document parsing.

Format dispatch and PDF-specific policies live in focused modules. This facade
keeps the established import and monkeypatch surface stable for callers.
"""

# ruff: noqa: F401 -- legacy private imports are intentionally re-exported.

from __future__ import annotations

from rag.ingestion.parsers.docling.adapter import DoclingProgressCallback
from .document_dispatch import (
    CONNECTOR_RECORD_CONTENT_TYPE as CONNECTOR_RECORD_CONTENT_TYPE,
    DOCX_CONTENT_TYPE as DOCX_CONTENT_TYPE,
    JPEG_CONTENT_TYPE as JPEG_CONTENT_TYPE,
    JSON_CONTENT_TYPE as JSON_CONTENT_TYPE,
    PDF_CONTENT_TYPE as PDF_CONTENT_TYPE,
    PNG_CONTENT_TYPE as PNG_CONTENT_TYPE,
    DocumentParserOperations,
    PageProgressCallback as PageProgressCallback,
    PdfImageReviewRequired as PdfImageReviewRequired,
    parse_document_with_operations,
    resume_pdf_image_review_with_operations,
)
from rag.ingestion.parsers.images import (
    ImageAnalyzer,
    ImageAssetStore,
    ImageProgressCallback,
    ImageSource,
    PdfVisualSourceResult,
    docx_image_sources as docx_image_sources,
    image_dimensions as image_dimensions,
    image_source_candidate_key as image_source_candidate_key,
    image_sources_to_items as image_sources_to_items,
    parse_image_document as parse_image_document,
    pdf_image_sources as pdf_image_sources,
    pdf_page_image_sources as pdf_page_image_sources,
    pdf_scanned_visual_region_sources as pdf_scanned_visual_region_sources,
    pdf_visual_sources as pdf_visual_sources,
    _vision_analysis_payload as _vision_analysis_payload,
)
from .models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from rag.ingestion.parsers.pdf.fallback import (
    parse_pdf_with_ocr_fallback as _parse_pdf_with_ocr_fallback,
    parse_pdf_with_vision_fallback as _parse_pdf_with_vision_fallback_impl,
    pdf_parser_config as _pdf_parser_config,
)
from rag.ingestion.parsers.pdf.image_processing import (
    DEFAULT_PDF_IMAGE_MAX_FULL_PAGE_FALLBACKS as DEFAULT_PDF_IMAGE_MAX_FULL_PAGE_FALLBACKS,
    PDF_IMAGE_FULL_PAGE_AREA_RATIO as PDF_IMAGE_FULL_PAGE_AREA_RATIO,
    PDF_IMAGE_MIN_FIGURE_AREA_RATIO as PDF_IMAGE_MIN_FIGURE_AREA_RATIO,
    PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO as PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO,
    PDF_IMAGE_WEAK_TEXT_CHARS as PDF_IMAGE_WEAK_TEXT_CHARS,
    PdfImageSelection as PdfImageSelection,
    _bbox_left as _bbox_left,
    _bbox_position as _bbox_position,
    _bbox_top as _bbox_top,
    _image_insert_index as _image_insert_index,
    _is_full_page_fallback_source as _is_full_page_fallback_source,
    _is_weak_text_source as _is_weak_text_source,
    _item_page as _item_page,
    _item_position_key as _item_position_key,
    _parsed_text_chars_by_page as _parsed_text_chars_by_page,
    _pdf_image_analysis_score as _pdf_image_analysis_score,
    append_image_outputs as _append_image_outputs,
    select_pdf_image_sources_for_analysis as _select_pdf_image_sources_for_analysis,
    pdf_visual_source_set as _pdf_visual_sources_impl,
)
from rag.ingestion.parsers.pdf.layout_repair import (
    MIN_VISION_LAYOUT_CHARS as MIN_VISION_LAYOUT_CHARS,
    MIN_VISION_LAYOUT_CONFIDENCE as MIN_VISION_LAYOUT_CONFIDENCE,
    VISION_LAYOUT_ORDER_FLAGS as VISION_LAYOUT_ORDER_FLAGS,
    VISION_LAYOUT_REPAIR_FLAGS as VISION_LAYOUT_REPAIR_FLAGS,
    VisionLayoutProgressCallback as VisionLayoutProgressCallback,
    _analysis_blocks as _analysis_blocks,
    _analysis_confidence as _analysis_confidence,
    _analysis_quality_flags as _analysis_quality_flags,
    _apply_vision_layout_replacements as _apply_vision_layout_replacements,
    _block_bbox as _block_bbox,
    _block_confidence as _block_confidence,
    _block_text as _block_text,
    _block_type as _block_type,
    _block_value as _block_value,
    _emit_vision_layout_progress as _emit_vision_layout_progress,
    _has_ordering_repair_flags as _has_ordering_repair_flags,
    _is_vision_layout_repair_flag as _is_vision_layout_repair_flag,
    _item_type_for_vision_block as _item_type_for_vision_block,
    _items_by_page as _items_by_page,
    _items_text as _items_text,
    _layout_analysis_needs_original_retry as _layout_analysis_needs_original_retry,
    _layout_analysis_signal_score as _layout_analysis_signal_score,
    _layout_analysis_text_chars as _layout_analysis_text_chars,
    _text_char_count as _text_char_count,
    _vision_layout_candidate_pages as _vision_layout_candidate_pages,
    _vision_layout_decision as _vision_layout_decision,
    _vision_layout_items_from_analysis as _vision_layout_items_from_analysis,
    _with_layout_analysis_flags as _with_layout_analysis_flags,
    log_skipped_vision_layout_repair as _log_skipped_vision_layout_repair,
    repair_pdf_complex_layout_with_vision as _repair_pdf_complex_layout_with_vision_impl,
)
def _parse_pdf_with_vision_fallback(
    file_bytes: bytes,
    *,
    image_context: tuple[str, ImageAssetStore, ImageAnalyzer] | None,
    parser_config: dict[str, object],
    parse_error: Exception,
    image_progress_callback: ImageProgressCallback | None = None,
) -> DocumentParseResult | None:
    return _parse_pdf_with_vision_fallback_impl(
        file_bytes,
        image_context=image_context,
        parser_config=parser_config,
        parse_error=parse_error,
        image_progress_callback=image_progress_callback,
        image_source_factory=pdf_image_sources,
        items_factory=image_sources_to_items,
    )


def _repair_pdf_complex_layout_with_vision(
    file_bytes: bytes,
    parsed: DocumentParseResult,
    *,
    image_context: tuple[str, ImageAssetStore, ImageAnalyzer],
    progress_callback: VisionLayoutProgressCallback | None = None,
) -> DocumentParseResult:
    return _repair_pdf_complex_layout_with_vision_impl(
        file_bytes,
        parsed,
        image_context=image_context,
        progress_callback=progress_callback,
        page_source_factory=pdf_page_image_sources,
        dimension_reader=image_dimensions,
        analysis_payload_factory=_vision_analysis_payload,
    )


def _pdf_visual_sources(
    file_bytes: bytes,
    *,
    parsed: DocumentParseResult,
    scanned_visual_region_enabled: bool,
    scanned_visual_min_area_ratio: float,
    scanned_visual_max_regions_per_page: int,
    scanned_visual_text_mask_padding_px: int,
) -> PdfVisualSourceResult:
    return _pdf_visual_sources_impl(
        file_bytes,
        parsed=parsed,
        scanned_visual_region_enabled=scanned_visual_region_enabled,
        scanned_visual_min_area_ratio=scanned_visual_min_area_ratio,
        scanned_visual_max_regions_per_page=scanned_visual_max_regions_per_page,
        scanned_visual_text_mask_padding_px=scanned_visual_text_mask_padding_px,
        visual_source_factory=pdf_visual_sources,
        image_source_factory=pdf_image_sources,
        scanned_source_factory=pdf_scanned_visual_region_sources,
    )


def _operations() -> DocumentParserOperations:
    return DocumentParserOperations(
        parse_pdf_with_ocr_fallback=_parse_pdf_with_ocr_fallback,
        parse_pdf_with_vision_fallback=_parse_pdf_with_vision_fallback,
        repair_pdf_complex_layout_with_vision=_repair_pdf_complex_layout_with_vision,
        log_skipped_vision_layout_repair=_log_skipped_vision_layout_repair,
        pdf_parser_config=_pdf_parser_config,
        pdf_visual_sources=_pdf_visual_sources,
        select_pdf_image_sources_for_analysis=_select_pdf_image_sources_for_analysis,
        image_sources_to_items=image_sources_to_items,
        append_image_outputs=_append_image_outputs,
    )


def parse_document(
    file_bytes: bytes,
    *,
    content_type: str | None,
    file_path: str,
    min_chars_per_page: int,
    ingestion_quality_preset: str = "fast",
    weak_page_threshold: int = 5,
    full_doc_weak_page_ratio: float = 0.25,
    layered_docling_max_pages: int = 40,
    layered_docling_max_page_ratio: float | None = None,
    prefer_full_document_docling: bool = False,
    layered_docling_batch_pages: int = 4,
    page_progress_callback: PageProgressCallback | None = None,
    docling_progress_callback: DoclingProgressCallback | None = None,
    vision_layout_progress_callback: VisionLayoutProgressCallback | None = None,
    image_progress_callback: ImageProgressCallback | None = None,
    pdf_image_analysis_max_images: int | None = None,
    pdf_image_analysis_max_full_page_fallbacks: int
    | None = DEFAULT_PDF_IMAGE_MAX_FULL_PAGE_FALLBACKS,
    pdf_image_review_threshold: int | None = None,
    scanned_visual_region_enabled: bool = True,
    scanned_visual_min_area_ratio: float = 0.03,
    scanned_visual_max_regions_per_page: int = -1,
    scanned_visual_text_mask_padding_px: int = 8,
    vision_layout_repair_enabled: bool = False,
    doc_id: str | None = None,
    image_asset_store: ImageAssetStore | None = None,
    image_analyzer: ImageAnalyzer | None = None,
) -> DocumentParseResult:
    return parse_document_with_operations(
        _operations(),
        file_bytes,
        content_type=content_type,
        file_path=file_path,
        min_chars_per_page=min_chars_per_page,
        ingestion_quality_preset=ingestion_quality_preset,
        weak_page_threshold=weak_page_threshold,
        full_doc_weak_page_ratio=full_doc_weak_page_ratio,
        layered_docling_max_pages=layered_docling_max_pages,
        layered_docling_max_page_ratio=layered_docling_max_page_ratio,
        prefer_full_document_docling=prefer_full_document_docling,
        layered_docling_batch_pages=layered_docling_batch_pages,
        page_progress_callback=page_progress_callback,
        docling_progress_callback=docling_progress_callback,
        vision_layout_progress_callback=vision_layout_progress_callback,
        image_progress_callback=image_progress_callback,
        pdf_image_analysis_max_images=pdf_image_analysis_max_images,
        pdf_image_analysis_max_full_page_fallbacks=pdf_image_analysis_max_full_page_fallbacks,
        pdf_image_review_threshold=pdf_image_review_threshold,
        scanned_visual_region_enabled=scanned_visual_region_enabled,
        scanned_visual_min_area_ratio=scanned_visual_min_area_ratio,
        scanned_visual_max_regions_per_page=scanned_visual_max_regions_per_page,
        scanned_visual_text_mask_padding_px=scanned_visual_text_mask_padding_px,
        vision_layout_repair_enabled=vision_layout_repair_enabled,
        doc_id=doc_id,
        image_asset_store=image_asset_store,
        image_analyzer=image_analyzer,
    )


def resume_pdf_image_review(
    parsed_items: list[ParsedPdfItem],
    approved_sources: list[ImageSource],
    *,
    doc_id: str,
    image_asset_store: ImageAssetStore,
    image_analyzer: ImageAnalyzer,
    candidate_count: int | None = None,
    image_progress_callback: ImageProgressCallback | None = None,
) -> DocumentParseResult:
    return resume_pdf_image_review_with_operations(
        _operations(),
        parsed_items,
        approved_sources,
        doc_id=doc_id,
        image_asset_store=image_asset_store,
        image_analyzer=image_analyzer,
        candidate_count=candidate_count,
        image_progress_callback=image_progress_callback,
    )
