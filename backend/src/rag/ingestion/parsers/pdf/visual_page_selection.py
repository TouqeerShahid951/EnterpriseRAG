"""Page classification and source selection for scanned PDF visuals."""

from __future__ import annotations

import re

from rag.ingestion.errors import WorkerStepError
from rag.ingestion.parsers.images.contracts import ImageSource, ScannedVisualRegionResult
from rag.ingestion.parsers.images.sources import fitz_module
from rag.ingestion.parsers.models import BBox, ParsedPdfItem
from rag.ingestion.parsers.pdf.visual_region_detection import scanned_visual_regions_for_page
from rag.ingestion.parsers.pdf.visual_source_mapping import visual_region_sources_from_regions

VISUAL_CUE_PATTERN = re.compile(
    r"\b("
    r"fig(?:ure)?|diagram|schematic|drawing|illustration|image|photo|photograph|plate|map|chart|graph|"
    r"signature|stamp|seal|logo|symbol|insignia|emblem|vehicle|tank|armou?red|aircraft|drone|missile|"
    r"launcher|radar|ship|vessel"
    r")\b",
    re.IGNORECASE,
)
DOMAIN_VISUAL_CUE_PATTERN = re.compile(
    r"\b(tank|armou?red|vehicle|aircraft|drone|missile|launcher|radar|ship|vessel|insignia|emblem|symbol)\b",
    re.IGNORECASE,
)


def pdf_scanned_visual_region_sources(
    file_bytes: bytes,
    *,
    parsed_items: list[ParsedPdfItem],
    image_sources: list[ImageSource],
    enabled: bool,
    min_area_ratio: float,
    max_regions_per_page: int,
    text_mask_padding_px: int,
) -> ScannedVisualRegionResult:
    page_numbers = document_page_numbers(parsed_items, image_sources)
    full_page_sources = full_page_sources_by_page(image_sources)
    embedded_sources = embedded_sources_by_page(image_sources)
    page_text_chars = parsed_text_chars_by_page(parsed_items)
    text_bboxes = parsed_text_bboxes_by_page(parsed_items)
    visual_cues = visual_cue_bboxes_by_page(parsed_items)
    domain_visual_cue_pages = domain_visual_cue_pages_for_items(parsed_items)
    class_counts: dict[str, int] = {}
    crop_sources: list[ImageSource] = []
    visual_region_pages: set[int] = set()
    fallback_pages: set[int] = set()
    candidate_count = 0
    skipped_tiny_count = 0
    skipped_text_only_count = 0
    ambiguous_count = 0
    cue_region_count = 0
    small_region_count = 0

    if not enabled:
        for page_no in sorted(page_numbers):
            increment(
                class_counts,
                page_class_without_scanned_detection(
                    page_no, full_page_sources, embedded_sources
                ),
            )
        return ScannedVisualRegionResult(sources=[], page_class_counts=class_counts)

    fitz = fitz_module()
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            for page_no in sorted(page_numbers):
                full_page_source = full_page_sources.get(page_no)
                if full_page_source is None:
                    increment(
                        class_counts,
                        "native_mixed"
                        if embedded_sources.get(page_no)
                        else "native_text_only",
                    )
                    continue
                weak_text = page_text_chars.get(page_no, 0) < 120
                boxes = text_bboxes.get(page_no, [])
                if not boxes:
                    class_name = "scanned_image_only" if weak_text else "ambiguous"
                    increment(class_counts, class_name)
                    fallback_pages.add(page_no)
                    ambiguous_count += 0 if weak_text else 1
                    continue
                try:
                    page = document.load_page(page_no - 1)
                    regions, tiny_count, ambiguous, cue_count, small_count = (
                        scanned_visual_regions_for_page(
                            page,
                            boxes,
                            visual_cue_bboxes=visual_cues.get(page_no, []),
                            domain_visual_cue=page_no in domain_visual_cue_pages,
                            min_area_ratio=max(0.0, min_area_ratio),
                            max_regions=max_regions_per_page,
                            text_mask_padding_px=max(0, text_mask_padding_px),
                        )
                    )
                except Exception:
                    increment(class_counts, "ambiguous")
                    fallback_pages.add(page_no)
                    ambiguous_count += 1
                    continue
                candidate_count += len(regions) + tiny_count
                skipped_tiny_count += tiny_count
                cue_region_count += cue_count
                small_region_count += small_count
                if ambiguous:
                    ambiguous_count += 1
                if regions:
                    increment(class_counts, "scanned_mixed")
                    visual_region_pages.add(page_no)
                    crop_sources.extend(
                        visual_region_sources_from_regions(
                            page_no=page_no,
                            regions=regions,
                            full_page_quality_flags=full_page_source.quality_flags,
                        )
                    )
                    continue
                if weak_text:
                    increment(class_counts, "scanned_image_only")
                    fallback_pages.add(page_no)
                else:
                    increment(class_counts, "scanned_text_only")
                    skipped_text_only_count += 1
    except Exception as exc:
        raise WorkerStepError(
            "pdf_scanned_visual_region_extract_failed",
            "PyMuPDF failed to extract scanned page visual regions.",
        ) from exc

    return ScannedVisualRegionResult(
        sources=crop_sources,
        page_class_counts=class_counts,
        candidate_count=candidate_count,
        selected_count=len(crop_sources),
        whole_page_fallback_count=len(fallback_pages),
        skipped_text_only_count=skipped_text_only_count,
        skipped_tiny_count=skipped_tiny_count,
        ambiguous_count=ambiguous_count,
        cue_region_count=cue_region_count,
        small_region_count=small_region_count,
        visual_region_pages=frozenset(visual_region_pages),
        whole_page_fallback_pages=frozenset(fallback_pages),
    )


def document_page_numbers(
    parsed_items: list[ParsedPdfItem], image_sources: list[ImageSource]
) -> set[int]:
    pages = {
        page
        for item in parsed_items
        for page in (item.page_start, item.page_end)
        if isinstance(page, int) and page > 0
    }
    pages.update(
        source.page
        for source in image_sources
        if isinstance(source.page, int) and source.page > 0
    )
    return pages


def full_page_sources_by_page(sources: list[ImageSource]) -> dict[int, ImageSource]:
    result: dict[int, ImageSource] = {}
    for source in sources:
        if source.page is None or not is_full_page_pdf_source(source):
            continue
        current = result.get(source.page)
        if current is None or (source.page_area_ratio or 0.0) > (
            current.page_area_ratio or 0.0
        ):
            result[source.page] = source
    return result


def embedded_sources_by_page(
    sources: list[ImageSource],
) -> dict[int, list[ImageSource]]:
    result: dict[int, list[ImageSource]] = {}
    for source in sources:
        if source.page is None or is_full_page_pdf_source(source):
            continue
        result.setdefault(source.page, []).append(source)
    return result


def page_class_without_scanned_detection(
    page_no: int,
    full_page_sources: dict[int, ImageSource],
    embedded_sources: dict[int, list[ImageSource]],
) -> str:
    if full_page_sources.get(page_no) is not None:
        return "ambiguous"
    return "native_mixed" if embedded_sources.get(page_no) else "native_text_only"


def is_full_page_pdf_source(source: ImageSource) -> bool:
    return (
        source.source_kind in {"pdf_page_image", "pdf_page_layout"}
        or "full_page_image_candidate" in source.quality_flags
        or (source.page_area_ratio is not None and source.page_area_ratio >= 0.75)
    )


def parsed_text_chars_by_page(items: list[ParsedPdfItem]) -> dict[int, int]:
    chars_by_page: dict[int, int] = {}
    for item in items:
        if item.item_type == "image_text":
            continue
        text_chars = len(" ".join(str(item.text or "").split()))
        if text_chars <= 0:
            continue
        for page in item_pages(item):
            chars_by_page[page] = chars_by_page.get(page, 0) + text_chars
    return chars_by_page


def parsed_text_bboxes_by_page(items: list[ParsedPdfItem]) -> dict[int, list[BBox]]:
    boxes_by_page: dict[int, list[BBox]] = {}
    for item in items:
        if item.item_type == "image_text" or item.bbox is None:
            continue
        for page in item_pages(item):
            boxes_by_page.setdefault(page, []).append(item.bbox)
    return boxes_by_page


def visual_cue_bboxes_by_page(items: list[ParsedPdfItem]) -> dict[int, list[BBox]]:
    boxes_by_page: dict[int, list[BBox]] = {}
    for item in items:
        if item.bbox is None or not VISUAL_CUE_PATTERN.search(item.text or ""):
            continue
        for page in item_pages(item):
            boxes_by_page.setdefault(page, []).append(item.bbox)
    return boxes_by_page


def domain_visual_cue_pages_for_items(items: list[ParsedPdfItem]) -> set[int]:
    pages: set[int] = set()
    for item in items:
        if not DOMAIN_VISUAL_CUE_PATTERN.search(item.text or ""):
            continue
        pages.update(item_pages(item))
    return pages


def item_pages(item: ParsedPdfItem) -> list[int]:
    pages = [
        page
        for page in (item.page_start, item.page_end)
        if isinstance(page, int) and page > 0
    ]
    if not pages:
        return []
    return list(range(min(pages), max(pages) + 1))


def increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1
