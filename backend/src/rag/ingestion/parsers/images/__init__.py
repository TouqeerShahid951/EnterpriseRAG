"""Compatibility facade for ingestion image parsing.

Image parsing is implemented in responsibility-focused modules. Imports from this
module remain stable for callers while they migrate to the owning modules.
"""

from __future__ import annotations

from rag.ingestion.parsers.pdf import visual_regions as _visual_regions
from rag.ingestion.parsers.images.analysis import (
    VISION_ANALYSIS_MAX_LONG_EDGE,
    VISION_ANALYSIS_OCR_MAX_LONG_EDGE,
    VISION_RETRY_MIN_CONFIDENCE,
    image_item_text as _image_item_text,
    image_sources_to_items,
    parse_image_document,
    vision_analysis_payload as _vision_analysis_payload,
)
from rag.ingestion.parsers.images.contracts import (
    JPEG_CONTENT_TYPE,
    PNG_CONTENT_TYPE,
    ImageAnalysisResult,
    ImageAnalyzer,
    ImageAssetStore,
    ImageProgressCallback,
    ImageSource,
    PdfVisualSourceResult,
    ScannedVisualRegionResult,
    image_source_candidate_key,
)
from rag.ingestion.parsers.images.normalization import (
    image_dimensions,
    normalize_image,
)
from rag.ingestion.parsers.images.sources import (
    docx_image_sources,
    pdf_image_source_kind_and_flags as _pdf_image_source_kind_and_flags,
    pdf_image_sources,
    pdf_page_image_sources,
)
from rag.ingestion.parsers.layout import prepare_page_layout
from rag.ingestion.parsers.models import BBox
from rag.ingestion.parsers.pdf.image_candidates import (
    PDF_IMAGE_FULL_PAGE_AREA_RATIO,
    PDF_IMAGE_MIN_FIGURE_AREA_RATIO,
    PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO,
    PDF_IMAGE_WEAK_TEXT_CHARS,
    pdf_visual_sources,
)
from rag.ingestion.parsers.pdf.visual_regions import (
    DOMAIN_VISUAL_CUE_PATTERN,
    LAYOUT_VISUAL_LABELS,
    VISUAL_CUE_PATTERN,
    VisualRegion as _VisualRegion,
    pdf_scanned_visual_region_sources,
)


def _scanned_visual_regions_for_page(
    page: object,
    text_bboxes: list[BBox],
    *,
    visual_cue_bboxes: list[BBox],
    domain_visual_cue: bool,
    min_area_ratio: float,
    max_regions: int,
    text_mask_padding_px: int,
) -> tuple[list[_VisualRegion], int, bool, int, int]:
    """Delegate while preserving the facade's patchable layout hook."""
    return _visual_regions.scanned_visual_regions_for_page(
        page,
        text_bboxes,
        visual_cue_bboxes=visual_cue_bboxes,
        domain_visual_cue=domain_visual_cue,
        min_area_ratio=min_area_ratio,
        max_regions=max_regions,
        text_mask_padding_px=text_mask_padding_px,
        prepare_page_layout_fn=prepare_page_layout,
    )


__all__ = [
    "DOMAIN_VISUAL_CUE_PATTERN",
    "ImageAnalysisResult",
    "ImageAnalyzer",
    "ImageAssetStore",
    "ImageProgressCallback",
    "ImageSource",
    "JPEG_CONTENT_TYPE",
    "LAYOUT_VISUAL_LABELS",
    "PDF_IMAGE_FULL_PAGE_AREA_RATIO",
    "PDF_IMAGE_MIN_FIGURE_AREA_RATIO",
    "PDF_IMAGE_MIN_WEAK_PAGE_AREA_RATIO",
    "PDF_IMAGE_WEAK_TEXT_CHARS",
    "PNG_CONTENT_TYPE",
    "PdfVisualSourceResult",
    "ScannedVisualRegionResult",
    "VISION_ANALYSIS_MAX_LONG_EDGE",
    "VISION_ANALYSIS_OCR_MAX_LONG_EDGE",
    "VISION_RETRY_MIN_CONFIDENCE",
    "VISUAL_CUE_PATTERN",
    "docx_image_sources",
    "image_dimensions",
    "image_source_candidate_key",
    "image_sources_to_items",
    "normalize_image",
    "parse_image_document",
    "pdf_image_sources",
    "pdf_page_image_sources",
    "pdf_scanned_visual_region_sources",
    "pdf_visual_sources",
    "_image_item_text",
    "_pdf_image_source_kind_and_flags",
    "_scanned_visual_regions_for_page",
    "_vision_analysis_payload",
]
