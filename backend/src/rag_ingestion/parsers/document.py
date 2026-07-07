"""Generic document parser dispatch for upload ingestion."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Callable
from uuid import uuid4

from ..errors import UnsupportedDocumentError, UnsupportedPdfError, WorkerStepError
from .connector_record import parse_connector_record_document
from .docling_adapter import DoclingProgressCallback, parse_docling_docx, parse_docling_pdf
from .hierarchy import apply_hierarchy
from .images import (
    ImageAnalyzer,
    ImageProgressCallback,
    ImageAssetStore,
    ImageSource,
    PdfVisualSourceResult,
    ScannedVisualRegionResult,
    docx_image_sources,
    image_dimensions,
    image_source_candidate_key,
    image_sources_to_items,
    parse_image_document,
    pdf_image_sources,
    pdf_page_image_sources,
    pdf_scanned_visual_region_sources,
    pdf_visual_sources,
    _vision_analysis_payload,
)
from .json import parse_json_document
from .models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from .pdf import parse_pdf_document
from .provenance import base_report, parser_item_counts, parser_page_counts, quality_flag_counts

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
JSON_CONTENT_TYPE = "application/json"
CONNECTOR_RECORD_CONTENT_TYPE = "application/vnd.agenticrag.connector-record+json"
PageProgressCallback = Callable[[int, int], None]
VisionLayoutProgressCallback = Callable[[dict[str, object]], None]
logger = logging.getLogger(__name__)

PDF_IMAGE_WEAK_TEXT_CHARS = 120
PDF_IMAGE_FULL_PAGE_AREA_RATIO = 0.75
PDF_IMAGE_MIN_FIGURE_AREA_RATIO = 0.08
PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO = 0.02
DEFAULT_PDF_IMAGE_MAX_FULL_PAGE_FALLBACKS = None


@dataclass(frozen=True)
class PdfImageSelection:
    sources: list[ImageSource]
    source_scores: dict[str, int] = field(default_factory=dict)
    skipped_unnecessary_count: int = 0
    skipped_duplicate_count: int = 0
    skipped_limit_count: int = 0
    skipped_full_page_fallback_count: int = 0
    skipped_review_count: int = 0

    @property
    def skipped_count(self) -> int:
        return (
            self.skipped_unnecessary_count
            + self.skipped_duplicate_count
            + self.skipped_limit_count
            + self.skipped_full_page_fallback_count
            + self.skipped_review_count
        )


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


VISION_LAYOUT_REPAIR_FLAGS = {
    "collapsed_measurement",
    "docling_page_budget_exceeded",
    "docling_page_repair_failed",
    "docling_page_repair_unavailable",
    "docling_unavailable",
    "flattened_table_text",
    "form_like_layout",
    "image_only_page",
    "invoice_like_layout",
    "missing_item_provenance",
    "multi_column_layout",
    "native_text_low_coverage",
    "reading_order_ambiguous",
    "rotated_page",
    "rotated_text",
    "scanned_or_handwritten_candidate",
    "structured_table_too_small",
    "table_caption_without_structured_table",
    "table_chunk_without_markdown",
    "table_region_without_structured_rows",
    "table_structure_low_confidence",
}
VISION_LAYOUT_ORDER_FLAGS = {
    "form_like_layout",
    "invoice_like_layout",
    "multi_column_layout",
    "reading_order_ambiguous",
    "table_caption_without_structured_table",
    "table_chunk_without_markdown",
    "table_structure_low_confidence",
}
MIN_VISION_LAYOUT_CHARS = 40
MIN_VISION_LAYOUT_CONFIDENCE = 0.55


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
    pdf_image_analysis_max_full_page_fallbacks: int | None = DEFAULT_PDF_IMAGE_MAX_FULL_PAGE_FALLBACKS,
    pdf_image_review_threshold: int | None = None,
    pdf_image_review_approved_keys: set[str] | None = None,
    scanned_visual_region_enabled: bool = True,
    scanned_visual_min_area_ratio: float = 0.03,
    scanned_visual_max_regions_per_page: int = -1,
    scanned_visual_text_mask_padding_px: int = 8,
    vision_layout_repair_enabled: bool = False,
    doc_id: str | None = None,
    image_asset_store: ImageAssetStore | None = None,
    image_analyzer: ImageAnalyzer | None = None,
) -> DocumentParseResult:
    kind = _document_kind(content_type, file_path)
    if kind == "connector_record":
        return parse_connector_record_document(file_bytes)
    if kind == "json" or (kind == "pdf" and _looks_like_json_bytes(file_bytes)):
        return parse_json_document(file_bytes)
    image_context = _image_context(doc_id, image_asset_store, image_analyzer)
    if kind == "pdf":
        parser_config = _pdf_parser_config(
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
            parsed = _parse_pdf_with_ocr_fallback(
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
            fallback = _parse_pdf_with_vision_fallback(
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
            parsed = _repair_pdf_complex_layout_with_vision(
                file_bytes,
                parsed,
                image_context=image_context,
                progress_callback=vision_layout_progress_callback,
            )
        else:
            _log_skipped_vision_layout_repair(parsed)
        visual_sources = _pdf_visual_sources(
            file_bytes,
            parsed=parsed,
            scanned_visual_region_enabled=scanned_visual_region_enabled,
            scanned_visual_min_area_ratio=scanned_visual_min_area_ratio,
            scanned_visual_max_regions_per_page=scanned_visual_max_regions_per_page,
            scanned_visual_text_mask_padding_px=scanned_visual_text_mask_padding_px,
        )
        image_sources_for_selection = visual_sources.image_sources
        scanned_visual_regions = visual_sources.scanned_visual_regions
        image_selection = _select_pdf_image_sources_for_analysis(
            image_sources_for_selection,
            parsed.items,
            pdf_image_analysis_max_images,
            max_full_page_fallbacks=pdf_image_analysis_max_full_page_fallbacks,
            scanned_visual_region_pages=scanned_visual_regions.visual_region_pages,
            scanned_visual_fallback_pages=scanned_visual_regions.whole_page_fallback_pages,
        )
        if pdf_image_review_approved_keys is not None:
            image_selection = _filter_pdf_image_selection_for_review(image_selection, pdf_image_review_approved_keys)
        elif (
            pdf_image_review_threshold is not None
            and pdf_image_review_threshold > 0
            and len(image_selection.sources) > pdf_image_review_threshold
        ):
            raise PdfImageReviewRequired(parsed=parsed, visual_sources=visual_sources, image_selection=image_selection)
        image_items, image_assets = image_sources_to_items(
            image_selection.sources,
            doc_id=image_context[0],
            store=image_context[1],
            analyzer=image_context[2],
            start_index=len(parsed.items),
            progress_callback=image_progress_callback,
        )
        return _append_image_outputs(
            parsed,
            image_items=image_items,
            image_assets=image_assets,
            image_candidate_count=visual_sources.image_candidate_count,
            image_selected_count=len(image_selection.sources),
            skipped_image_count=image_selection.skipped_count + visual_sources.skipped_unnecessary_count,
            skipped_unnecessary_count=image_selection.skipped_unnecessary_count + visual_sources.skipped_unnecessary_count,
            skipped_duplicate_count=image_selection.skipped_duplicate_count,
            skipped_limit_count=image_selection.skipped_limit_count,
            skipped_full_page_fallback_count=image_selection.skipped_full_page_fallback_count,
            skipped_review_count=image_selection.skipped_review_count,
            scanned_visual_regions=scanned_visual_regions,
        )
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
                progress_callback=image_progress_callback,
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
    image_items, image_assets = image_sources_to_items(
        approved_sources,
        doc_id=doc_id,
        store=image_asset_store,
        analyzer=image_analyzer,
        start_index=len(parsed_items),
        progress_callback=image_progress_callback,
    )
    skipped_review_count = max(0, candidate_count - len(approved_sources)) if candidate_count is not None else 0
    parsed = DocumentParseResult(
        items=parsed_items,
        provenance=base_report(
            document_kind="pdf",
            page_count=_page_count(parsed_items),
            primary_parser="review_resume",
            secondary_parser="vision",
            routing_mode="image_review_resume",
            config={},
            items=parsed_items,
        ),
    )
    return _append_image_outputs(
        parsed,
        image_items=image_items,
        image_assets=image_assets,
        image_candidate_count=candidate_count,
        image_selected_count=len(approved_sources),
        skipped_image_count=skipped_review_count,
        skipped_review_count=skipped_review_count,
    )


def _parse_pdf_with_ocr_fallback(
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
                config=_pdf_parser_config(
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
                fallback={"from": "layered", "to": "docling", "reason": "native_text_unsupported"},
            ),
        )


def _parse_pdf_with_vision_fallback(
    file_bytes: bytes,
    *,
    image_context: tuple[str, ImageAssetStore, ImageAnalyzer] | None,
    parser_config: dict[str, object],
    parse_error: Exception,
    image_progress_callback: ImageProgressCallback | None = None,
) -> DocumentParseResult | None:
    if image_context is None:
        return None
    try:
        image_items, image_assets = image_sources_to_items(
            pdf_image_sources(file_bytes),
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
    items = _renumber_items(_vision_fallback_items(image_items, parse_error=parse_error))
    return DocumentParseResult(
        items=items,
        provenance=base_report(
            document_kind="pdf",
            page_count=_page_count(items),
            primary_parser="vision",
            secondary_parser=None,
            routing_mode="vision_fallback",
            config=parser_config,
            items=items,
            fallback={
                "from": "layered_docling_ocr",
                "to": "vision",
                "reason": _parse_error_code(parse_error),
            },
            errors=[{"component": "parser", "code": _parse_error_code(parse_error)}],
        ) | {"image_asset_count": len(image_assets)},
        assets=image_assets,
    )


def _repair_pdf_complex_layout_with_vision(
    file_bytes: bytes,
    parsed: DocumentParseResult,
    *,
    image_context: tuple[str, ImageAssetStore, ImageAnalyzer],
    progress_callback: VisionLayoutProgressCallback | None = None,
) -> DocumentParseResult:
    analyzer = image_context[2]
    analyze_layout = getattr(analyzer, "analyze_layout", None)
    if not callable(analyze_layout):
        logger.info("Vision layout repair unavailable: analyzer has no analyze_layout method")
        return parsed
    candidate_pages = _vision_layout_candidate_pages(parsed.items)
    if not candidate_pages:
        logger.debug("Vision layout repair skipped: no candidate pages")
        return parsed
    try:
        page_sources = pdf_page_image_sources(file_bytes, candidate_pages)
    except Exception:
        logger.exception("Vision layout repair skipped: failed to render candidate pages")
        return parsed
    if not page_sources:
        logger.info("Vision layout repair skipped: no page renders for %s candidate pages", len(candidate_pages))
        return parsed
    logger.info("Vision layout repair enabled for %s candidate pages", len(page_sources))
    items_by_page = _items_by_page(parsed.items)
    replacements: dict[int, list[ParsedPdfItem]] = {}
    repair_assets: list[ParsedImageAsset] = []
    evaluations: list[dict[str, object]] = []
    for index, source in enumerate(page_sources, start=1):
        if source.page is None:
            continue
        page_items = items_by_page.get(source.page, [])
        _emit_vision_layout_progress(
            progress_callback,
            status="running",
            current=index - 1,
            total=len(page_sources),
            page=source.page,
        )
        try:
            analysis = _analyze_layout_source(source, analyze_layout)
        except Exception:
            logger.exception("Vision layout repair failed for PDF page %s", source.page)
            evaluations.append({"page": source.page, "decision": "skipped", "reason": "vision_layout_request_failed"})
            _emit_vision_layout_progress(
                progress_callback,
                status="failed",
                current=index,
                total=len(page_sources),
                page=source.page,
            )
            continue
        candidate_items = _vision_layout_items_from_analysis(
            analysis,
            source=source,
            asset_id=None,
        )
        decision = _vision_layout_decision(page_items, candidate_items, analysis)
        evaluations.append({"page": source.page, **decision})
        if not decision["use"]:
            logger.info("Vision layout repair skipped PDF page %s: %s", source.page, decision["reason"])
            _emit_vision_layout_progress(
                progress_callback,
                status="skipped",
                current=index,
                total=len(page_sources),
                page=source.page,
                reason=str(decision["reason"]),
            )
            continue
        try:
            width, height = image_dimensions(source.content)
        except WorkerStepError:
            logger.info("Vision layout repair skipped PDF page %s: image parse failed", source.page)
            evaluations.append({"page": source.page, "decision": "skipped", "reason": "vision_layout_image_parse_failed"})
            _emit_vision_layout_progress(
                progress_callback,
                status="skipped",
                current=index,
                total=len(page_sources),
                page=source.page,
                reason="image parse failed",
            )
            continue
        asset_id = str(uuid4())
        object_path = image_context[1].put_image_asset(
            doc_id=image_context[0],
            asset_id=asset_id,
            filename=source.filename,
            content=source.content,
            content_type=source.content_type,
        )
        repair_assets.append(
            ParsedImageAsset(
                id=asset_id,
                source_kind=source.source_kind,
                object_path=object_path,
                content_type=source.content_type,
                content_hash=hashlib.sha256(source.content).hexdigest(),
                page=source.page,
                bbox=source.bbox,
                width=width,
                height=height,
                extracted_text=_items_text(candidate_items) or None,
                caption="Vision layout repair page render",
                confidence=_analysis_confidence(analysis),
                quality_flags=sorted(
                    {*source.quality_flags, *_analysis_quality_flags(analysis), "source:vision", "vision_layout_repair"}
                ),
            )
        )
        replacements[source.page] = _vision_layout_items_from_analysis(
            analysis,
            source=source,
            asset_id=asset_id,
        )
        logger.info("Vision layout repair accepted PDF page %s: %s", source.page, decision["reason"])
        _emit_vision_layout_progress(
            progress_callback,
            status="complete",
            current=index,
            total=len(page_sources),
            page=source.page,
        )
    if not replacements:
        return parsed
    return _apply_vision_layout_replacements(
        parsed,
        replacements=replacements,
        repair_assets=repair_assets,
        candidate_pages=candidate_pages,
        evaluations=evaluations,
    )


def _analyze_layout_source(source: ImageSource, analyze_layout: Callable[..., object]) -> object:
    content, content_type, flags = _vision_analysis_payload(source)
    analysis = analyze_layout(content=content, content_type=content_type)
    if "vision_input_resized" not in flags or not _layout_analysis_needs_original_retry(analysis):
        return _with_layout_analysis_flags(analysis, flags)
    original_analysis = analyze_layout(content=source.content, content_type=source.content_type)
    if not _layout_analysis_needs_original_retry(original_analysis) or _layout_analysis_signal_score(original_analysis) >= _layout_analysis_signal_score(analysis):
        return _with_layout_analysis_flags(original_analysis, ["vision_layout_retry_original"])
    return _with_layout_analysis_flags(analysis, [*flags, "vision_layout_retry_original_no_improvement"])


def _layout_analysis_needs_original_retry(analysis: object) -> bool:
    flags = _analysis_quality_flags(analysis)
    if any(flag.startswith("vision_layout_failed") for flag in flags) or "vision_layout_empty_response" in flags:
        return True
    confidence = _analysis_confidence(analysis)
    if confidence is not None and confidence < MIN_VISION_LAYOUT_CONFIDENCE:
        return True
    return _layout_analysis_text_chars(analysis) < MIN_VISION_LAYOUT_CHARS


def _layout_analysis_signal_score(analysis: object) -> float:
    score = float(_layout_analysis_text_chars(analysis))
    confidence = _analysis_confidence(analysis)
    if confidence is not None:
        score += confidence * 50
    if any(flag.startswith("vision_layout_failed") for flag in _analysis_quality_flags(analysis)):
        score -= 100
    return score


def _with_layout_analysis_flags(analysis: object, extra_flags: list[str]) -> object:
    if not extra_flags:
        return analysis
    flags = sorted({*_analysis_quality_flags(analysis), *extra_flags})
    try:
        return replace(analysis, quality_flags=flags)
    except TypeError:
        return SimpleNamespace(blocks=_analysis_blocks(analysis), confidence=_analysis_confidence(analysis), quality_flags=flags)


def _layout_analysis_text_chars(analysis: object) -> int:
    return _text_char_count("\n".join(_block_text(block) for block in _analysis_blocks(analysis)))


def _vision_layout_candidate_pages(items: list[ParsedPdfItem]) -> set[int]:
    pages: set[int] = set()
    for item in items:
        if not item.page_start:
            continue
        if any(_is_vision_layout_repair_flag(flag) for flag in item.quality_flags):
            pages.add(item.page_start)
    return pages


def _is_vision_layout_repair_flag(flag: str) -> bool:
    return flag in VISION_LAYOUT_REPAIR_FLAGS or flag.startswith(
        ("low_parsed_text_coverage", "docling_layout_failed", "docling_page_repair_failed")
    )


def _items_by_page(items: list[ParsedPdfItem]) -> dict[int, list[ParsedPdfItem]]:
    grouped: dict[int, list[ParsedPdfItem]] = {}
    for item in items:
        if item.page_start is None:
            continue
        grouped.setdefault(item.page_start, []).append(item)
    return grouped


def _vision_layout_items_from_analysis(
    analysis: object,
    *,
    source: ImageSource,
    asset_id: str | None,
) -> list[ParsedPdfItem]:
    blocks = _analysis_blocks(analysis)
    confidence = _analysis_confidence(analysis)
    flags = sorted(
        {
            *source.quality_flags,
            *_analysis_quality_flags(analysis),
            "source:vision",
            "vision_layout_repair",
            "docling_layout_repaired",
            "layout_repair_source:vision",
        }
    )
    items: list[ParsedPdfItem] = []
    for block in blocks:
        text = _block_text(block)
        if not text:
            continue
        block_type = _block_type(block)
        items.append(
            ParsedPdfItem(
                index=len(items),
                text=text,
                item_type=_item_type_for_vision_block(block_type),
                page_start=source.page,
                page_end=source.page,
                bbox=_block_bbox(block, source.bbox),
                parser="vision_layout",
                quality_flags=flags,
                confidence=_block_confidence(block) if _block_confidence(block) is not None else confidence,
                image_asset_id=asset_id,
                image_source_kind=source.source_kind,
                image_content_type=source.content_type,
                extraction_method="vision_layout_repair",
            )
        )
    return items


def _vision_layout_decision(
    existing_items: list[ParsedPdfItem],
    vision_items: list[ParsedPdfItem],
    analysis: object,
) -> dict[str, object]:
    existing_chars = _text_char_count(_items_text(existing_items))
    vision_chars = _text_char_count(_items_text(vision_items))
    confidence = _analysis_confidence(analysis)
    metrics: dict[str, object] = {
        "use": False,
        "decision": "skipped",
        "reason": "not_better",
        "existing_chars": existing_chars,
        "vision_chars": vision_chars,
        "vision_blocks": len(vision_items),
        "confidence": confidence,
    }
    if vision_chars < MIN_VISION_LAYOUT_CHARS:
        return {**metrics, "reason": "too_little_vision_text"}
    if confidence is not None and confidence < MIN_VISION_LAYOUT_CONFIDENCE:
        return {**metrics, "reason": "low_vision_confidence"}
    if existing_chars <= 0:
        return {**metrics, "use": True, "decision": "repaired", "reason": "missing_existing_text"}
    gain = vision_chars - existing_chars
    if gain >= max(80, int(existing_chars * 0.15)):
        return {**metrics, "use": True, "decision": "repaired", "reason": "vision_recovered_more_text"}
    if _has_ordering_repair_flags(existing_items) and len(vision_items) >= 2 and vision_chars >= int(existing_chars * 0.9):
        return {**metrics, "use": True, "decision": "repaired", "reason": "vision_repaired_reading_order"}
    return metrics


def _has_ordering_repair_flags(items: list[ParsedPdfItem]) -> bool:
    return any(flag in VISION_LAYOUT_ORDER_FLAGS for item in items for flag in item.quality_flags)


def _apply_vision_layout_replacements(
    parsed: DocumentParseResult,
    *,
    replacements: dict[int, list[ParsedPdfItem]],
    repair_assets: list[ParsedImageAsset],
    candidate_pages: set[int],
    evaluations: list[dict[str, object]],
) -> DocumentParseResult:
    replaced_pages = set(replacements)
    inserted_pages: set[int] = set()
    items: list[ParsedPdfItem] = []
    for item in parsed.items:
        page = item.page_start
        if page in replacements:
            if page not in inserted_pages:
                items.extend(replacements[page])
                inserted_pages.add(page)
            continue
        items.append(item)
    for page in sorted(replaced_pages - inserted_pages):
        items.extend(replacements[page])
    items = apply_hierarchy(_renumber_items(items))
    assets = [*parsed.assets, *repair_assets]
    provenance = {
        **parsed.provenance,
        "secondary_parser": "vision",
        "parser_item_counts": parser_item_counts(items),
        "parser_page_counts": parser_page_counts(items),
        "quality_flag_counts": quality_flag_counts(items),
        "image_asset_count": len(assets),
        "vision_layout_repair": {
            "candidate_pages": sorted(candidate_pages),
            "repaired_pages": sorted(replaced_pages),
            "skipped_pages": sorted(candidate_pages - replaced_pages),
            "evaluations": evaluations[:20],
        },
    }
    return DocumentParseResult(items=items, provenance=provenance, assets=assets)


def _log_skipped_vision_layout_repair(parsed: DocumentParseResult) -> None:
    candidate_pages = _vision_layout_candidate_pages(parsed.items)
    if candidate_pages:
        logger.info(
            "Vision layout repair disabled by ingestion config; skipped %s candidate pages",
            len(candidate_pages),
        )


def _emit_vision_layout_progress(
    callback: VisionLayoutProgressCallback | None,
    *,
    status: str,
    current: int,
    total: int,
    page: int,
    reason: str | None = None,
) -> None:
    if callback is None:
        return
    event: dict[str, object] = {
        "phase": "vision_layout_repair",
        "status": status,
        "current": current,
        "total": total,
        "page": page,
    }
    if reason:
        event["reason"] = reason
    callback(event)


def _analysis_blocks(analysis: object) -> list[object]:
    blocks = getattr(analysis, "blocks", None)
    return blocks if isinstance(blocks, list) else []


def _analysis_confidence(analysis: object) -> float | None:
    confidence = getattr(analysis, "confidence", None)
    if isinstance(confidence, (int, float)):
        return max(0.0, min(1.0, float(confidence)))
    values = [_block_confidence(block) for block in _analysis_blocks(analysis)]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _analysis_quality_flags(analysis: object) -> list[str]:
    flags = getattr(analysis, "quality_flags", None)
    return [str(flag) for flag in flags] if isinstance(flags, list) else []


def _block_text(block: object) -> str:
    text = _block_value(block, "text")
    return " ".join(str(text or "").split())


def _block_type(block: object) -> str:
    value = _block_value(block, "block_type")
    if value is None:
        value = _block_value(block, "type")
    normalized = str(value or "text").strip().lower().replace("-", "_")
    if normalized in {"heading", "table", "caption", "form_field"}:
        return normalized
    return "text"


def _block_confidence(block: object) -> float | None:
    value = _block_value(block, "confidence")
    if not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def _block_bbox(block: object, page_bbox: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
    value = _block_value(block, "bbox")
    if not isinstance(value, list) or len(value) != 4:
        return page_bbox
    try:
        left, top, right, bottom = (float(item) for item in value)
    except (TypeError, ValueError):
        return page_bbox
    if right <= left or bottom <= top:
        return page_bbox
    if page_bbox is not None and all(0.0 <= item <= 1.0 for item in (left, top, right, bottom)):
        page_left, page_top, page_right, page_bottom = page_bbox
        width = page_right - page_left
        height = page_bottom - page_top
        return (
            page_left + left * width,
            page_top + top * height,
            page_left + right * width,
            page_top + bottom * height,
        )
    return (left, top, right, bottom)


def _block_value(block: object, key: str) -> object:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def _item_type_for_vision_block(block_type: str) -> str:
    if block_type in {"heading", "table", "caption"}:
        return block_type
    return "text"


def _items_text(items: list[ParsedPdfItem]) -> str:
    return "\n\n".join(item.text for item in items if item.text).strip()


def _text_char_count(text: str) -> int:
    return len("".join(text.split()))


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


def _pdf_parser_config(
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


def _vision_fallback_items(items: list[ParsedPdfItem], *, parse_error: Exception) -> list[ParsedPdfItem]:
    flags = {"vision_pdf_page_fallback", _parse_error_quality_flag(parse_error)}
    return [
        replace(item, quality_flags=sorted({*item.quality_flags, *flags}))
        for item in items
    ]


def _parse_error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return str(code) if code else type(exc).__name__


def _parse_error_quality_flag(exc: Exception) -> str:
    code = _parse_error_code(exc)
    if code == "ocr_dependency_missing":
        return "docling_ocr_unavailable"
    if code == "unsupported_pdf_type":
        return "docling_ocr_empty"
    return "docling_ocr_failed"


def _looks_like_json_bytes(file_bytes: bytes) -> bool:
    sample = file_bytes[:4096]
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]
    sample = sample.lstrip()
    return sample.startswith((b"{", b"["))


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


def _scanned_visual_region_sources(
    file_bytes: bytes,
    *,
    parsed: DocumentParseResult,
    image_sources: list[ImageSource],
    enabled: bool,
    min_area_ratio: float,
    max_regions_per_page: int,
    text_mask_padding_px: int,
) -> ScannedVisualRegionResult:
    try:
        return pdf_scanned_visual_region_sources(
            file_bytes,
            parsed_items=parsed.items,
            image_sources=image_sources,
            enabled=enabled,
            min_area_ratio=min_area_ratio,
            max_regions_per_page=max_regions_per_page,
            text_mask_padding_px=text_mask_padding_px,
        )
    except Exception:
        logger.exception("Scanned visual region extraction skipped")
        return ScannedVisualRegionResult(sources=[], page_class_counts={})


def _pdf_visual_sources(
    file_bytes: bytes,
    *,
    parsed: DocumentParseResult,
    scanned_visual_region_enabled: bool,
    scanned_visual_min_area_ratio: float,
    scanned_visual_max_regions_per_page: int,
    scanned_visual_text_mask_padding_px: int,
) -> PdfVisualSourceResult:
    try:
        return pdf_visual_sources(
            file_bytes,
            parsed_items=parsed.items,
            scanned_visual_region_enabled=scanned_visual_region_enabled,
            scanned_visual_min_area_ratio=scanned_visual_min_area_ratio,
            scanned_visual_max_regions_per_page=scanned_visual_max_regions_per_page,
            scanned_visual_text_mask_padding_px=scanned_visual_text_mask_padding_px,
        )
    except WorkerStepError:
        image_sources = pdf_image_sources(file_bytes)
        scanned_visual_regions = _scanned_visual_region_sources(
            file_bytes,
            parsed=parsed,
            image_sources=image_sources,
            enabled=scanned_visual_region_enabled,
            min_area_ratio=scanned_visual_min_area_ratio,
            max_regions_per_page=scanned_visual_max_regions_per_page,
            text_mask_padding_px=scanned_visual_text_mask_padding_px,
        )
        return PdfVisualSourceResult(
            image_sources=[*image_sources, *scanned_visual_regions.sources],
            scanned_visual_regions=scanned_visual_regions,
            image_candidate_count=len(image_sources) + len(scanned_visual_regions.sources),
        )


def _append_image_outputs(
    parsed: DocumentParseResult,
    *,
    image_items: list[ParsedPdfItem],
    image_assets: list[ParsedImageAsset],
    image_candidate_count: int | None = None,
    image_selected_count: int | None = None,
    skipped_image_count: int = 0,
    skipped_unnecessary_count: int = 0,
    skipped_duplicate_count: int = 0,
    skipped_limit_count: int = 0,
    skipped_full_page_fallback_count: int = 0,
    skipped_review_count: int = 0,
    scanned_visual_regions: ScannedVisualRegionResult | None = None,
) -> DocumentParseResult:
    if not image_items and not image_assets and skipped_image_count <= 0:
        return parsed
    assets = [*parsed.assets, *image_assets]
    items = _renumber_items(_merge_items_by_page_position(parsed.items, image_items))
    image_provenance = {"image_asset_count": len(assets)}
    if image_candidate_count is not None:
        image_provenance["image_analysis_candidate_count"] = image_candidate_count
    if image_selected_count is not None:
        image_provenance["image_analysis_selected_count"] = image_selected_count
    if skipped_image_count > 0:
        image_provenance["image_analysis_skipped_count"] = skipped_image_count
    if skipped_unnecessary_count > 0:
        image_provenance["image_analysis_skipped_unnecessary_count"] = skipped_unnecessary_count
    if skipped_duplicate_count > 0:
        image_provenance["image_analysis_skipped_duplicate_count"] = skipped_duplicate_count
    if skipped_limit_count > 0:
        image_provenance["image_analysis_skipped_limit_count"] = skipped_limit_count
    if skipped_full_page_fallback_count > 0:
        image_provenance["image_analysis_skipped_full_page_fallback_count"] = skipped_full_page_fallback_count
    if skipped_review_count > 0:
        image_provenance["image_analysis_skipped_review_count"] = skipped_review_count
    if scanned_visual_regions is not None:
        image_provenance["scanned_page_class_counts"] = scanned_visual_regions.page_class_counts
        image_provenance["scanned_visual_candidate_count"] = scanned_visual_regions.candidate_count
        image_provenance["scanned_visual_selected_count"] = scanned_visual_regions.selected_count
        image_provenance["scanned_visual_whole_page_fallback_count"] = scanned_visual_regions.whole_page_fallback_count
        if scanned_visual_regions.skipped_text_only_count > 0:
            image_provenance["scanned_visual_skipped_text_only_count"] = scanned_visual_regions.skipped_text_only_count
        if scanned_visual_regions.skipped_tiny_count > 0:
            image_provenance["scanned_visual_skipped_tiny_count"] = scanned_visual_regions.skipped_tiny_count
        if scanned_visual_regions.ambiguous_count > 0:
            image_provenance["scanned_visual_ambiguous_count"] = scanned_visual_regions.ambiguous_count
        if scanned_visual_regions.cue_region_count > 0:
            image_provenance["scanned_visual_cue_region_count"] = scanned_visual_regions.cue_region_count
        if scanned_visual_regions.small_region_count > 0:
            image_provenance["scanned_visual_small_region_count"] = scanned_visual_regions.small_region_count
    provenance = {
        **parsed.provenance,
        "secondary_parser": "vision" if image_items or image_assets else parsed.provenance.get("secondary_parser"),
        "parser_item_counts": parser_item_counts(items),
        "parser_page_counts": parser_page_counts(items),
        "quality_flag_counts": quality_flag_counts(items),
        **image_provenance,
    }
    return DocumentParseResult(items=items, provenance=provenance, assets=assets)


def _merge_items_by_page_position(parsed_items: list[ParsedPdfItem], image_items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    merged = list(parsed_items)
    for image_item in sorted(image_items, key=_item_position_key):
        merged.insert(_image_insert_index(merged, image_item), image_item)
    return merged


def _image_insert_index(items: list[ParsedPdfItem], image_item: ParsedPdfItem) -> int:
    page = _item_page(image_item)
    if page is None:
        return len(items)
    last_same_page_index: int | None = None
    for index, item in enumerate(items):
        item_page = _item_page(item)
        if item_page is None:
            continue
        if item_page > page:
            return index
        if item_page < page:
            continue
        last_same_page_index = index
        if image_item.bbox is not None and item.bbox is not None and _bbox_position(item.bbox) > _bbox_position(image_item.bbox):
            return index
    return len(items) if last_same_page_index is None else last_same_page_index + 1


def _item_position_key(item: ParsedPdfItem) -> tuple[int, float, float, int]:
    page = _item_page(item)
    return (page if page is not None else 10**9, _bbox_top(item.bbox), _bbox_left(item.bbox), item.index)


def _item_page(item: ParsedPdfItem) -> int | None:
    return item.page_start if isinstance(item.page_start, int) and item.page_start > 0 else None


def _bbox_position(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return (_bbox_top(bbox), _bbox_left(bbox))


def _bbox_top(bbox: tuple[float, float, float, float] | None) -> float:
    return float(bbox[1]) if bbox is not None else 0.0


def _bbox_left(bbox: tuple[float, float, float, float] | None) -> float:
    return float(bbox[0]) if bbox is not None else 0.0


def _select_pdf_image_sources_for_analysis(
    sources: list[ImageSource],
    parsed_items: list[ParsedPdfItem],
    max_images: int | None,
    *,
    max_full_page_fallbacks: int | None = DEFAULT_PDF_IMAGE_MAX_FULL_PAGE_FALLBACKS,
    scanned_visual_region_pages: frozenset[int] = frozenset(),
    scanned_visual_fallback_pages: frozenset[int] = frozenset(),
) -> PdfImageSelection:
    page_text_chars = _parsed_text_chars_by_page(parsed_items)
    selected: list[tuple[int, int, ImageSource]] = []
    seen_hashes: set[str] = set()
    skipped_unnecessary_count = 0
    skipped_duplicate_count = 0
    skipped_full_page_fallback_count = 0
    full_page_fallback_count = 0
    full_page_fallback_limit = None if max_full_page_fallbacks is None or max_full_page_fallbacks < 0 else max_full_page_fallbacks
    for order, source in enumerate(sources):
        score = _pdf_image_analysis_score(
            source,
            page_text_chars,
            scanned_visual_region_pages=scanned_visual_region_pages,
            scanned_visual_fallback_pages=scanned_visual_fallback_pages,
        )
        if score <= 0:
            skipped_unnecessary_count += 1
            continue
        content_hash = hashlib.sha256(source.content).hexdigest()
        if content_hash in seen_hashes and not _is_weak_text_source(source, page_text_chars):
            skipped_duplicate_count += 1
            continue
        seen_hashes.add(content_hash)
        if _is_full_page_fallback_source(source, page_text_chars, scanned_visual_fallback_pages):
            if full_page_fallback_limit is not None and full_page_fallback_count >= full_page_fallback_limit:
                skipped_full_page_fallback_count += 1
                continue
            full_page_fallback_count += 1
        selected.append((score, order, source))
    source_scores = {image_source_candidate_key(source): score for score, _, source in selected}
    if max_images is None or max_images < 0 or len(selected) <= max_images:
        return PdfImageSelection(
            sources=[source for _, _, source in selected],
            source_scores=source_scores,
            skipped_unnecessary_count=skipped_unnecessary_count,
            skipped_duplicate_count=skipped_duplicate_count,
            skipped_full_page_fallback_count=skipped_full_page_fallback_count,
        )
    if max_images == 0:
        return PdfImageSelection(
            sources=[],
            source_scores={},
            skipped_unnecessary_count=skipped_unnecessary_count,
            skipped_duplicate_count=skipped_duplicate_count,
            skipped_full_page_fallback_count=skipped_full_page_fallback_count,
            skipped_limit_count=len(selected),
        )
    selected_orders = {
        order
        for _, order, _ in sorted(selected, key=lambda item: (-item[0], item[1]))[:max_images]
    }
    limited_sources = [source for _, order, source in selected if order in selected_orders]
    limited_scores = {image_source_candidate_key(source): score for score, order, source in selected if order in selected_orders}
    return PdfImageSelection(
        sources=limited_sources,
        source_scores=limited_scores,
        skipped_unnecessary_count=skipped_unnecessary_count,
        skipped_duplicate_count=skipped_duplicate_count,
        skipped_full_page_fallback_count=skipped_full_page_fallback_count,
        skipped_limit_count=len(selected) - len(limited_sources),
    )


def _filter_pdf_image_selection_for_review(selection: PdfImageSelection, approved_keys: set[str]) -> PdfImageSelection:
    approved_sources = [source for source in selection.sources if image_source_candidate_key(source) in approved_keys]
    approved_scores = {
        image_source_candidate_key(source): selection.source_scores.get(image_source_candidate_key(source), 0)
        for source in approved_sources
    }
    return replace(
        selection,
        sources=approved_sources,
        source_scores=approved_scores,
        skipped_review_count=selection.skipped_review_count + len(selection.sources) - len(approved_sources),
    )


def _parsed_text_chars_by_page(items: list[ParsedPdfItem]) -> dict[int, int]:
    chars_by_page: dict[int, int] = {}
    for item in items:
        if item.item_type == "image_text":
            continue
        text_chars = len(" ".join(str(item.text or "").split()))
        if text_chars <= 0:
            continue
        pages = [
            page
            for page in (item.page_start, item.page_end)
            if isinstance(page, int) and page > 0
        ]
        if not pages:
            continue
        for page in range(min(pages), max(pages) + 1):
            chars_by_page[page] = chars_by_page.get(page, 0) + text_chars
    return chars_by_page


def _pdf_image_analysis_score(
    source: ImageSource,
    page_text_chars: dict[int, int],
    *,
    scanned_visual_region_pages: frozenset[int] = frozenset(),
    scanned_visual_fallback_pages: frozenset[int] = frozenset(),
) -> int:
    weak_page = _is_weak_text_source(source, page_text_chars)
    area_ratio = source.page_area_ratio
    full_page = (
        source.source_kind in {"pdf_page_image", "pdf_page_layout"}
        or "full_page_image_candidate" in source.quality_flags
        or (area_ratio is not None and area_ratio >= PDF_IMAGE_FULL_PAGE_AREA_RATIO)
    )
    if source.source_kind == "pdf_scanned_visual_region":
        return 120
    if source.source_kind == "pdf_page_layout":
        return 130
    if full_page:
        if source.page in scanned_visual_fallback_pages:
            return 80
        if source.page in scanned_visual_region_pages:
            return 0
        return 80 if weak_page else 0
    if weak_page and (area_ratio is None or area_ratio >= PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO):
        return 100
    if "large_image_candidate" in source.quality_flags:
        return 110
    if area_ratio is not None and area_ratio >= PDF_IMAGE_MIN_FIGURE_AREA_RATIO:
        return 110
    return 0


def _is_full_page_fallback_source(
    source: ImageSource,
    page_text_chars: dict[int, int],
    scanned_visual_fallback_pages: frozenset[int],
) -> bool:
    if source.page is None:
        return False
    if source.source_kind == "pdf_page_layout":
        return False
    full_page = (
        source.source_kind == "pdf_page_image"
        or "full_page_image_candidate" in source.quality_flags
        or (source.page_area_ratio is not None and source.page_area_ratio >= PDF_IMAGE_FULL_PAGE_AREA_RATIO)
    )
    return full_page and (source.page in scanned_visual_fallback_pages or _is_weak_text_source(source, page_text_chars))


def _is_weak_text_source(source: ImageSource, page_text_chars: dict[int, int]) -> bool:
    if source.page is None:
        return False
    return page_text_chars.get(source.page, 0) < PDF_IMAGE_WEAK_TEXT_CHARS
