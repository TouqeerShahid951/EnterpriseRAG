"""Vision-based repair for PDF pages with complex or ambiguous layouts."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from types import SimpleNamespace
from typing import Callable
from uuid import uuid4

from ..errors import WorkerStepError
from .hierarchy import apply_hierarchy
from .images import (
    ImageAnalyzer,
    ImageAssetStore,
    ImageSource,
    image_dimensions,
    pdf_page_image_sources,
    _vision_analysis_payload,
)
from .models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from .pdf_image_processing import renumber_items
from .provenance import parser_item_counts, parser_page_counts, quality_flag_counts

VisionLayoutProgressCallback = Callable[[dict[str, object]], None]
logger = logging.getLogger(__name__)

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


def repair_pdf_complex_layout_with_vision(
    file_bytes: bytes,
    parsed: DocumentParseResult,
    *,
    image_context: tuple[str, ImageAssetStore, ImageAnalyzer],
    progress_callback: VisionLayoutProgressCallback | None = None,
    page_source_factory: Callable[
        [bytes, set[int]], list[ImageSource]
    ] = pdf_page_image_sources,
    dimension_reader: Callable[[bytes], tuple[int, int]] = image_dimensions,
    analysis_payload_factory: Callable[
        [ImageSource], tuple[bytes, str, list[str]]
    ] = _vision_analysis_payload,
) -> DocumentParseResult:
    analyzer = image_context[2]
    analyze_layout = getattr(analyzer, "analyze_layout", None)
    if not callable(analyze_layout):
        logger.info(
            "Vision layout repair unavailable: analyzer has no analyze_layout method"
        )
        return parsed
    candidate_pages = _vision_layout_candidate_pages(parsed.items)
    if not candidate_pages:
        logger.debug("Vision layout repair skipped: no candidate pages")
        return parsed
    try:
        page_sources = page_source_factory(file_bytes, candidate_pages)
    except Exception:
        logger.exception(
            "Vision layout repair skipped: failed to render candidate pages"
        )
        return parsed
    if not page_sources:
        logger.info(
            "Vision layout repair skipped: no page renders for %s candidate pages",
            len(candidate_pages),
        )
        return parsed
    logger.info(
        "Vision layout repair enabled for %s candidate pages", len(page_sources)
    )
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
            analysis = _analyze_layout_source(
                source, analyze_layout, analysis_payload_factory
            )
        except Exception:
            logger.exception("Vision layout repair failed for PDF page %s", source.page)
            evaluations.append(
                {
                    "page": source.page,
                    "decision": "skipped",
                    "reason": "vision_layout_request_failed",
                }
            )
            _emit_vision_layout_progress(
                progress_callback,
                status="failed",
                current=index,
                total=len(page_sources),
                page=source.page,
            )
            continue
        candidate_items = _vision_layout_items_from_analysis(
            analysis, source=source, asset_id=None
        )
        decision = _vision_layout_decision(page_items, candidate_items, analysis)
        evaluations.append({"page": source.page, **decision})
        if not decision["use"]:
            logger.info(
                "Vision layout repair skipped PDF page %s: %s",
                source.page,
                decision["reason"],
            )
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
            width, height = dimension_reader(source.content)
        except WorkerStepError:
            logger.info(
                "Vision layout repair skipped PDF page %s: image parse failed",
                source.page,
            )
            evaluations.append(
                {
                    "page": source.page,
                    "decision": "skipped",
                    "reason": "vision_layout_image_parse_failed",
                }
            )
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
                    {
                        *source.quality_flags,
                        *_analysis_quality_flags(analysis),
                        "source:vision",
                        "vision_layout_repair",
                    }
                ),
            )
        )
        replacements[source.page] = _vision_layout_items_from_analysis(
            analysis,
            source=source,
            asset_id=asset_id,
        )
        logger.info(
            "Vision layout repair accepted PDF page %s: %s",
            source.page,
            decision["reason"],
        )
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


def _analyze_layout_source(
    source: ImageSource,
    analyze_layout: Callable[..., object],
    analysis_payload_factory: Callable[
        [ImageSource], tuple[bytes, str, list[str]]
    ] = _vision_analysis_payload,
) -> object:
    content, content_type, flags = analysis_payload_factory(source)
    analysis = analyze_layout(content=content, content_type=content_type)
    if "vision_input_resized" not in flags or not _layout_analysis_needs_original_retry(
        analysis
    ):
        return _with_layout_analysis_flags(analysis, flags)
    original_analysis = analyze_layout(
        content=source.content, content_type=source.content_type
    )
    if not _layout_analysis_needs_original_retry(
        original_analysis
    ) or _layout_analysis_signal_score(
        original_analysis
    ) >= _layout_analysis_signal_score(analysis):
        return _with_layout_analysis_flags(
            original_analysis, ["vision_layout_retry_original"]
        )
    return _with_layout_analysis_flags(
        analysis, [*flags, "vision_layout_retry_original_no_improvement"]
    )


def _layout_analysis_needs_original_retry(analysis: object) -> bool:
    flags = _analysis_quality_flags(analysis)
    if (
        any(flag.startswith("vision_layout_failed") for flag in flags)
        or "vision_layout_empty_response" in flags
    ):
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
    if any(
        flag.startswith("vision_layout_failed")
        for flag in _analysis_quality_flags(analysis)
    ):
        score -= 100
    return score


def _with_layout_analysis_flags(analysis: object, extra_flags: list[str]) -> object:
    if not extra_flags:
        return analysis
    flags = sorted({*_analysis_quality_flags(analysis), *extra_flags})
    try:
        return replace(analysis, quality_flags=flags)
    except TypeError:
        return SimpleNamespace(
            blocks=_analysis_blocks(analysis),
            confidence=_analysis_confidence(analysis),
            quality_flags=flags,
        )


def _layout_analysis_text_chars(analysis: object) -> int:
    return _text_char_count(
        "\n".join(_block_text(block) for block in _analysis_blocks(analysis))
    )


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
        (
            "low_parsed_text_coverage",
            "docling_layout_failed",
            "docling_page_repair_failed",
        )
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
                confidence=_block_confidence(block)
                if _block_confidence(block) is not None
                else confidence,
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
        return {
            **metrics,
            "use": True,
            "decision": "repaired",
            "reason": "missing_existing_text",
        }
    gain = vision_chars - existing_chars
    if gain >= max(80, int(existing_chars * 0.15)):
        return {
            **metrics,
            "use": True,
            "decision": "repaired",
            "reason": "vision_recovered_more_text",
        }
    if (
        _has_ordering_repair_flags(existing_items)
        and len(vision_items) >= 2
        and vision_chars >= int(existing_chars * 0.9)
    ):
        return {
            **metrics,
            "use": True,
            "decision": "repaired",
            "reason": "vision_repaired_reading_order",
        }
    return metrics


def _has_ordering_repair_flags(items: list[ParsedPdfItem]) -> bool:
    return any(
        flag in VISION_LAYOUT_ORDER_FLAGS
        for item in items
        for flag in item.quality_flags
    )


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
    items = apply_hierarchy(renumber_items(items))
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


def log_skipped_vision_layout_repair(parsed: DocumentParseResult) -> None:
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


def _block_bbox(
    block: object,
    page_bbox: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    value = _block_value(block, "bbox")
    if not isinstance(value, list) or len(value) != 4:
        return page_bbox
    try:
        left, top, right, bottom = (float(item) for item in value)
    except (TypeError, ValueError):
        return page_bbox
    if right <= left or bottom <= top:
        return page_bbox
    if page_bbox is not None and all(
        0.0 <= item <= 1.0 for item in (left, top, right, bottom)
    ):
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
