"""Compatibility facade for scanned PDF visual-region parsing."""

from __future__ import annotations

from collections.abc import Callable as Callable
from dataclasses import dataclass as dataclass
from io import BytesIO as BytesIO
import math as math
import re as re

from ..errors import WorkerStepError as WorkerStepError
from .image_contracts import (
    ImageSource as ImageSource,
    PNG_CONTENT_TYPE as PNG_CONTENT_TYPE,
    ScannedVisualRegionResult as ScannedVisualRegionResult,
)
from .image_normalization import (
    bbox_area as bbox_area,
    bbox_from_value as bbox_from_value,
    normalized_image_source as normalized_image_source,
)
from .image_sources import fitz_module as fitz_module
from .layout import prepare_page_layout as prepare_page_layout
from .models import BBox as BBox, ParsedPdfItem as ParsedPdfItem
from .pdf_visual_component_detection import (
    connected_foreground_components,
    foreground_neighbors,
)
from .pdf_visual_page_selection import (
    DOMAIN_VISUAL_CUE_PATTERN,
    VISUAL_CUE_PATTERN,
    document_page_numbers,
    domain_visual_cue_pages_for_items,
    embedded_sources_by_page,
    full_page_sources_by_page,
    increment,
    is_full_page_pdf_source,
    item_pages,
    page_class_without_scanned_detection,
    parsed_text_bboxes_by_page,
    parsed_text_chars_by_page,
    pdf_scanned_visual_region_sources,
    visual_cue_bboxes_by_page,
)
from .pdf_visual_region_detection import scanned_visual_regions_for_page
from .pdf_visual_region_geometry import (
    LAYOUT_VISUAL_LABELS,
    VisualRegion,
    component_area_ratio,
    component_center_inside,
    layout_visual_regions_for_page,
    region_overlap,
    visual_cue_context_regions,
    visual_region_from_mask_bbox,
    visual_region_from_pdf_bbox,
    visual_region_from_pixel_bbox,
)
from .pdf_visual_source_mapping import visual_region_sources_from_regions

__all__ = [
    "BBox",
    "BytesIO",
    "Callable",
    "DOMAIN_VISUAL_CUE_PATTERN",
    "ImageSource",
    "LAYOUT_VISUAL_LABELS",
    "PNG_CONTENT_TYPE",
    "ParsedPdfItem",
    "ScannedVisualRegionResult",
    "VISUAL_CUE_PATTERN",
    "VisualRegion",
    "WorkerStepError",
    "bbox_area",
    "bbox_from_value",
    "component_area_ratio",
    "component_center_inside",
    "connected_foreground_components",
    "dataclass",
    "document_page_numbers",
    "domain_visual_cue_pages_for_items",
    "embedded_sources_by_page",
    "fitz_module",
    "foreground_neighbors",
    "full_page_sources_by_page",
    "increment",
    "is_full_page_pdf_source",
    "item_pages",
    "layout_visual_regions_for_page",
    "math",
    "normalized_image_source",
    "page_class_without_scanned_detection",
    "parsed_text_bboxes_by_page",
    "parsed_text_chars_by_page",
    "pdf_scanned_visual_region_sources",
    "prepare_page_layout",
    "re",
    "region_overlap",
    "scanned_visual_regions_for_page",
    "visual_cue_bboxes_by_page",
    "visual_cue_context_regions",
    "visual_region_from_mask_bbox",
    "visual_region_from_pdf_bbox",
    "visual_region_from_pixel_bbox",
    "visual_region_sources_from_regions",
]
