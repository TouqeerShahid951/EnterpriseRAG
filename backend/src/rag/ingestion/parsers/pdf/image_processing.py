"""PDF image candidate selection, merging, and provenance."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from typing import Callable

from rag.ingestion.errors import WorkerStepError
from rag.ingestion.parsers.images import (
    ImageSource,
    PdfVisualSourceResult,
    ScannedVisualRegionResult,
    image_source_candidate_key,
    pdf_image_sources,
    pdf_scanned_visual_region_sources,
    pdf_visual_sources,
)
from rag.ingestion.parsers.models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem
from rag.ingestion.parsers.provenance import parser_item_counts, parser_page_counts, quality_flag_counts

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


def page_count(items: list[ParsedPdfItem]) -> int:
    pages = [
        page
        for item in items
        for page in (item.page_start, item.page_end)
        if isinstance(page, int) and page > 0
    ]
    return max(pages) if pages else 0


def renumber_items(items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    return [replace(item, index=index) for index, item in enumerate(items)]


def scanned_visual_region_sources(
    file_bytes: bytes,
    *,
    parsed: DocumentParseResult,
    image_sources: list[ImageSource],
    enabled: bool,
    min_area_ratio: float,
    max_regions_per_page: int,
    text_mask_padding_px: int,
    source_factory: Callable[
        ..., ScannedVisualRegionResult
    ] = pdf_scanned_visual_region_sources,
) -> ScannedVisualRegionResult:
    try:
        return source_factory(
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


def pdf_visual_source_set(
    file_bytes: bytes,
    *,
    parsed: DocumentParseResult,
    scanned_visual_region_enabled: bool,
    scanned_visual_min_area_ratio: float,
    scanned_visual_max_regions_per_page: int,
    scanned_visual_text_mask_padding_px: int,
    visual_source_factory: Callable[..., PdfVisualSourceResult] = pdf_visual_sources,
    image_source_factory: Callable[[bytes], list[ImageSource]] = pdf_image_sources,
    scanned_source_factory: Callable[
        ..., ScannedVisualRegionResult
    ] = pdf_scanned_visual_region_sources,
) -> PdfVisualSourceResult:
    try:
        return visual_source_factory(
            file_bytes,
            parsed_items=parsed.items,
            scanned_visual_region_enabled=scanned_visual_region_enabled,
            scanned_visual_min_area_ratio=scanned_visual_min_area_ratio,
            scanned_visual_max_regions_per_page=scanned_visual_max_regions_per_page,
            scanned_visual_text_mask_padding_px=scanned_visual_text_mask_padding_px,
        )
    except WorkerStepError:
        image_sources = image_source_factory(file_bytes)
        scanned_visual_regions = scanned_visual_region_sources(
            file_bytes,
            parsed=parsed,
            image_sources=image_sources,
            enabled=scanned_visual_region_enabled,
            min_area_ratio=scanned_visual_min_area_ratio,
            max_regions_per_page=scanned_visual_max_regions_per_page,
            text_mask_padding_px=scanned_visual_text_mask_padding_px,
            source_factory=scanned_source_factory,
        )
        return PdfVisualSourceResult(
            image_sources=[*image_sources, *scanned_visual_regions.sources],
            scanned_visual_regions=scanned_visual_regions,
            image_candidate_count=len(image_sources)
            + len(scanned_visual_regions.sources),
        )


def append_image_outputs(
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
    items = renumber_items(merge_items_by_page_position(parsed.items, image_items))
    image_provenance = {"image_asset_count": len(assets)}
    if image_candidate_count is not None:
        image_provenance["image_analysis_candidate_count"] = image_candidate_count
    if image_selected_count is not None:
        image_provenance["image_analysis_selected_count"] = image_selected_count
    if skipped_image_count > 0:
        image_provenance["image_analysis_skipped_count"] = skipped_image_count
    if skipped_unnecessary_count > 0:
        image_provenance["image_analysis_skipped_unnecessary_count"] = (
            skipped_unnecessary_count
        )
    if skipped_duplicate_count > 0:
        image_provenance["image_analysis_skipped_duplicate_count"] = (
            skipped_duplicate_count
        )
    if skipped_limit_count > 0:
        image_provenance["image_analysis_skipped_limit_count"] = skipped_limit_count
    if skipped_full_page_fallback_count > 0:
        image_provenance["image_analysis_skipped_full_page_fallback_count"] = (
            skipped_full_page_fallback_count
        )
    if skipped_review_count > 0:
        image_provenance["image_analysis_skipped_review_count"] = skipped_review_count
    if scanned_visual_regions is not None:
        image_provenance["scanned_page_class_counts"] = (
            scanned_visual_regions.page_class_counts
        )
        image_provenance["scanned_visual_candidate_count"] = (
            scanned_visual_regions.candidate_count
        )
        image_provenance["scanned_visual_selected_count"] = (
            scanned_visual_regions.selected_count
        )
        image_provenance["scanned_visual_whole_page_fallback_count"] = (
            scanned_visual_regions.whole_page_fallback_count
        )
        if scanned_visual_regions.skipped_text_only_count > 0:
            image_provenance["scanned_visual_skipped_text_only_count"] = (
                scanned_visual_regions.skipped_text_only_count
            )
        if scanned_visual_regions.skipped_tiny_count > 0:
            image_provenance["scanned_visual_skipped_tiny_count"] = (
                scanned_visual_regions.skipped_tiny_count
            )
        if scanned_visual_regions.ambiguous_count > 0:
            image_provenance["scanned_visual_ambiguous_count"] = (
                scanned_visual_regions.ambiguous_count
            )
        if scanned_visual_regions.cue_region_count > 0:
            image_provenance["scanned_visual_cue_region_count"] = (
                scanned_visual_regions.cue_region_count
            )
        if scanned_visual_regions.small_region_count > 0:
            image_provenance["scanned_visual_small_region_count"] = (
                scanned_visual_regions.small_region_count
            )
    provenance = {
        **parsed.provenance,
        "secondary_parser": "vision"
        if image_items or image_assets
        else parsed.provenance.get("secondary_parser"),
        "parser_item_counts": parser_item_counts(items),
        "parser_page_counts": parser_page_counts(items),
        "quality_flag_counts": quality_flag_counts(items),
        **image_provenance,
    }
    return DocumentParseResult(items=items, provenance=provenance, assets=assets)


def merge_items_by_page_position(
    parsed_items: list[ParsedPdfItem], image_items: list[ParsedPdfItem]
) -> list[ParsedPdfItem]:
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
        if (
            image_item.bbox is not None
            and item.bbox is not None
            and _bbox_position(item.bbox) > _bbox_position(image_item.bbox)
        ):
            return index
    return len(items) if last_same_page_index is None else last_same_page_index + 1


def _item_position_key(item: ParsedPdfItem) -> tuple[int, float, float, int]:
    page = _item_page(item)
    return (
        page if page is not None else 10**9,
        _bbox_top(item.bbox),
        _bbox_left(item.bbox),
        item.index,
    )


def _item_page(item: ParsedPdfItem) -> int | None:
    return (
        item.page_start
        if isinstance(item.page_start, int) and item.page_start > 0
        else None
    )


def _bbox_position(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return (_bbox_top(bbox), _bbox_left(bbox))


def _bbox_top(bbox: tuple[float, float, float, float] | None) -> float:
    return float(bbox[1]) if bbox is not None else 0.0


def _bbox_left(bbox: tuple[float, float, float, float] | None) -> float:
    return float(bbox[0]) if bbox is not None else 0.0


def select_pdf_image_sources_for_analysis(
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
    full_page_fallback_limit = (
        None
        if max_full_page_fallbacks is None or max_full_page_fallbacks < 0
        else max_full_page_fallbacks
    )
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
        if content_hash in seen_hashes and not _is_weak_text_source(
            source, page_text_chars
        ):
            skipped_duplicate_count += 1
            continue
        seen_hashes.add(content_hash)
        if _is_full_page_fallback_source(
            source, page_text_chars, scanned_visual_fallback_pages
        ):
            if (
                full_page_fallback_limit is not None
                and full_page_fallback_count >= full_page_fallback_limit
            ):
                skipped_full_page_fallback_count += 1
                continue
            full_page_fallback_count += 1
        selected.append((score, order, source))
    source_scores = {
        image_source_candidate_key(source): score for score, _, source in selected
    }
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
        for _, order, _ in sorted(selected, key=lambda item: (-item[0], item[1]))[
            :max_images
        ]
    }
    limited_sources = [
        source for _, order, source in selected if order in selected_orders
    ]
    limited_scores = {
        image_source_candidate_key(source): score
        for score, order, source in selected
        if order in selected_orders
    }
    return PdfImageSelection(
        sources=limited_sources,
        source_scores=limited_scores,
        skipped_unnecessary_count=skipped_unnecessary_count,
        skipped_duplicate_count=skipped_duplicate_count,
        skipped_full_page_fallback_count=skipped_full_page_fallback_count,
        skipped_limit_count=len(selected) - len(limited_sources),
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
    if weak_page and (
        area_ratio is None or area_ratio >= PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO
    ):
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
        or (
            source.page_area_ratio is not None
            and source.page_area_ratio >= PDF_IMAGE_FULL_PAGE_AREA_RATIO
        )
    )
    return full_page and (
        source.page in scanned_visual_fallback_pages
        or _is_weak_text_source(source, page_text_chars)
    )


def _is_weak_text_source(source: ImageSource, page_text_chars: dict[int, int]) -> bool:
    if source.page is None:
        return False
    return page_text_chars.get(source.page, 0) < PDF_IMAGE_WEAK_TEXT_CHARS
