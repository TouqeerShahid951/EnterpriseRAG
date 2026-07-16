"""Document format dispatch and PDF image-review resumption."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..errors import UnsupportedDocumentError, WorkerStepError
from .connector_record import parse_connector_record_document
from rag.ingestion.parsers.docling.adapter import DoclingProgressCallback
from rag.ingestion.parsers.images import (
    ImageAnalyzer,
    ImageAssetStore,
    ImageProgressCallback,
    ImageSource,
    PdfVisualSourceResult,
    parse_image_document,
)
from .json import parse_json_document
from .models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from rag.ingestion.parsers.pdf.image_processing import (
    DEFAULT_PDF_IMAGE_MAX_FULL_PAGE_FALLBACKS,
    PdfImageSelection,
    page_count,
)
from rag.ingestion.parsers.pdf.layout_repair import VisionLayoutProgressCallback
from .provenance import base_report
from rag.ingestion.parsers.word import DOCX_CONTENT_TYPE, parse_word_document

PDF_CONTENT_TYPE = "application/pdf"
JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
JSON_CONTENT_TYPE = "application/json"
CONNECTOR_RECORD_CONTENT_TYPE = "application/vnd.agenticrag.connector-record+json"
PageProgressCallback = Callable[[int, int], None]


class PdfImageReviewRequired(RuntimeError):
    def __init__(
        self,
        *,
        parsed: DocumentParseResult,
        visual_sources: PdfVisualSourceResult,
        image_selection: PdfImageSelection,
    ) -> None:
        super().__init__("pdf image review required")
        self.parsed = parsed
        self.visual_sources = visual_sources
        self.image_selection = image_selection


@dataclass(frozen=True)
class DocumentParserOperations:
    """Facade operations that preserve the established document-module patch seams."""

    parse_pdf_with_ocr_fallback: Callable[..., DocumentParseResult]
    parse_pdf_with_vision_fallback: Callable[..., DocumentParseResult | None]
    repair_pdf_complex_layout_with_vision: Callable[..., DocumentParseResult]
    log_skipped_vision_layout_repair: Callable[[DocumentParseResult], None]
    pdf_parser_config: Callable[..., dict[str, object]]
    pdf_visual_sources: Callable[..., PdfVisualSourceResult]
    select_pdf_image_sources_for_analysis: Callable[..., PdfImageSelection]
    image_sources_to_items: Callable[
        ..., tuple[list[ParsedPdfItem], list[ParsedImageAsset]]
    ]
    append_image_outputs: Callable[..., DocumentParseResult]


def parse_document_with_operations(
    operations: DocumentParserOperations,
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
    kind = document_kind(content_type, file_path)
    if kind == "connector_record":
        return parse_connector_record_document(file_bytes)
    if kind == "json" or (kind == "pdf" and looks_like_json_bytes(file_bytes)):
        return parse_json_document(file_bytes)
    image_context = build_image_context(doc_id, image_asset_store, image_analyzer)
    if kind == "pdf":
        return _parse_pdf_document(
            operations,
            file_bytes,
            image_context=image_context,
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
        )
    if kind == "docx":
        return parse_word_document(
            file_bytes,
            image_context=image_context,
            image_items_factory=operations.image_sources_to_items,
            image_progress_callback=image_progress_callback,
        )
    if kind == "image":
        if image_context is None:
            raise WorkerStepError(
                "image_processing_unavailable",
                "Image processing dependencies are not configured.",
            )
        return parse_image_document(
            file_bytes,
            doc_id=image_context[0],
            store=image_context[1],
            analyzer=image_context[2],
            content_type=content_type,
            filename=file_path.rsplit("/", 1)[-1] or "upload",
        )
    raise UnsupportedDocumentError()


def _parse_pdf_document(
    operations: DocumentParserOperations,
    file_bytes: bytes,
    *,
    image_context: tuple[str, ImageAssetStore, ImageAnalyzer] | None,
    min_chars_per_page: int,
    ingestion_quality_preset: str,
    weak_page_threshold: int,
    full_doc_weak_page_ratio: float,
    layered_docling_max_pages: int,
    layered_docling_max_page_ratio: float | None,
    prefer_full_document_docling: bool,
    layered_docling_batch_pages: int,
    page_progress_callback: PageProgressCallback | None,
    docling_progress_callback: DoclingProgressCallback | None,
    vision_layout_progress_callback: VisionLayoutProgressCallback | None,
    image_progress_callback: ImageProgressCallback | None,
    pdf_image_analysis_max_images: int | None,
    pdf_image_analysis_max_full_page_fallbacks: int | None,
    pdf_image_review_threshold: int | None,
    scanned_visual_region_enabled: bool,
    scanned_visual_min_area_ratio: float,
    scanned_visual_max_regions_per_page: int,
    scanned_visual_text_mask_padding_px: int,
    vision_layout_repair_enabled: bool,
) -> DocumentParseResult:
    parser_config = operations.pdf_parser_config(
        min_chars_per_page=min_chars_per_page,
        ingestion_quality_preset=ingestion_quality_preset,
        weak_page_threshold=weak_page_threshold,
        full_doc_weak_page_ratio=full_doc_weak_page_ratio,
        layered_docling_max_pages=layered_docling_max_pages,
        layered_docling_max_page_ratio=layered_docling_max_page_ratio,
        prefer_full_document_docling=prefer_full_document_docling,
        layered_docling_batch_pages=layered_docling_batch_pages,
    )
    try:
        parsed = operations.parse_pdf_with_ocr_fallback(
            file_bytes,
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
        )
    except Exception as exc:
        fallback = operations.parse_pdf_with_vision_fallback(
            file_bytes,
            image_context=image_context,
            parser_config=parser_config,
            parse_error=exc,
            image_progress_callback=image_progress_callback,
        )
        if fallback is not None:
            return fallback
        raise
    if image_context is None:
        return parsed
    if vision_layout_repair_enabled:
        parsed = operations.repair_pdf_complex_layout_with_vision(
            file_bytes,
            parsed,
            image_context=image_context,
            progress_callback=vision_layout_progress_callback,
        )
    else:
        operations.log_skipped_vision_layout_repair(parsed)
    visual_sources = operations.pdf_visual_sources(
        file_bytes,
        parsed=parsed,
        scanned_visual_region_enabled=scanned_visual_region_enabled,
        scanned_visual_min_area_ratio=scanned_visual_min_area_ratio,
        scanned_visual_max_regions_per_page=scanned_visual_max_regions_per_page,
        scanned_visual_text_mask_padding_px=scanned_visual_text_mask_padding_px,
    )
    scanned_visual_regions = visual_sources.scanned_visual_regions
    image_selection = operations.select_pdf_image_sources_for_analysis(
        visual_sources.image_sources,
        parsed.items,
        pdf_image_analysis_max_images,
        max_full_page_fallbacks=pdf_image_analysis_max_full_page_fallbacks,
        scanned_visual_region_pages=scanned_visual_regions.visual_region_pages,
        scanned_visual_fallback_pages=scanned_visual_regions.whole_page_fallback_pages,
    )
    if (
        pdf_image_review_threshold is not None
        and pdf_image_review_threshold > 0
        and len(image_selection.sources) > pdf_image_review_threshold
    ):
        raise PdfImageReviewRequired(
            parsed=parsed,
            visual_sources=visual_sources,
            image_selection=image_selection,
        )
    image_items, image_assets = operations.image_sources_to_items(
        image_selection.sources,
        doc_id=image_context[0],
        store=image_context[1],
        analyzer=image_context[2],
        start_index=len(parsed.items),
        progress_callback=image_progress_callback,
    )
    return operations.append_image_outputs(
        parsed,
        image_items=image_items,
        image_assets=image_assets,
        image_candidate_count=visual_sources.image_candidate_count,
        image_selected_count=len(image_selection.sources),
        skipped_image_count=image_selection.skipped_count
        + visual_sources.skipped_unnecessary_count,
        skipped_unnecessary_count=image_selection.skipped_unnecessary_count
        + visual_sources.skipped_unnecessary_count,
        skipped_duplicate_count=image_selection.skipped_duplicate_count,
        skipped_limit_count=image_selection.skipped_limit_count,
        skipped_full_page_fallback_count=image_selection.skipped_full_page_fallback_count,
        skipped_review_count=image_selection.skipped_review_count,
        scanned_visual_regions=scanned_visual_regions,
    )


def resume_pdf_image_review_with_operations(
    operations: DocumentParserOperations,
    parsed_items: list[ParsedPdfItem],
    approved_sources: list[ImageSource],
    *,
    doc_id: str,
    image_asset_store: ImageAssetStore,
    image_analyzer: ImageAnalyzer,
    candidate_count: int | None = None,
    image_progress_callback: ImageProgressCallback | None = None,
) -> DocumentParseResult:
    image_items, image_assets = operations.image_sources_to_items(
        approved_sources,
        doc_id=doc_id,
        store=image_asset_store,
        analyzer=image_analyzer,
        start_index=len(parsed_items),
        progress_callback=image_progress_callback,
    )
    skipped_review_count = (
        max(0, candidate_count - len(approved_sources))
        if candidate_count is not None
        else 0
    )
    parsed = DocumentParseResult(
        items=parsed_items,
        provenance=base_report(
            document_kind="pdf",
            page_count=page_count(parsed_items),
            primary_parser="review_resume",
            secondary_parser="vision",
            routing_mode="image_review_resume",
            config={},
            items=parsed_items,
        ),
    )
    return operations.append_image_outputs(
        parsed,
        image_items=image_items,
        image_assets=image_assets,
        image_candidate_count=candidate_count,
        image_selected_count=len(approved_sources),
        skipped_image_count=skipped_review_count,
        skipped_review_count=skipped_review_count,
    )


def document_kind(content_type: str | None, file_path: str) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized == PDF_CONTENT_TYPE:
        return "pdf"
    if normalized == DOCX_CONTENT_TYPE:
        return "docx"
    if normalized in {JPEG_CONTENT_TYPE, PNG_CONTENT_TYPE}:
        return "image"
    if normalized == JSON_CONTENT_TYPE:
        return "json"
    if normalized == CONNECTOR_RECORD_CONTENT_TYPE:
        return "connector_record"
    lowered_path = file_path.lower()
    if lowered_path.endswith((".jpg", ".jpeg", ".png")):
        return "image"
    if lowered_path.endswith(".docx"):
        return "docx"
    if lowered_path.endswith(".json"):
        return "json"
    return "pdf" if lowered_path.endswith(".pdf") or not normalized else "unsupported"


def looks_like_json_bytes(file_bytes: bytes) -> bool:
    sample = file_bytes[:4096]
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]
    sample = sample.lstrip()
    return sample.startswith((b"{", b"["))


def build_image_context(
    doc_id: str | None,
    image_asset_store: ImageAssetStore | None,
    image_analyzer: ImageAnalyzer | None,
) -> tuple[str, ImageAssetStore, ImageAnalyzer] | None:
    if doc_id is None or image_asset_store is None or image_analyzer is None:
        return None
    return doc_id, image_asset_store, image_analyzer
