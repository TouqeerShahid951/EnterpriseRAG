"""Mapping detected PDF visual regions to normalized image sources."""

from __future__ import annotations

from ..errors import WorkerStepError
from .image_contracts import ImageSource, PNG_CONTENT_TYPE
from .image_normalization import normalized_image_source
from .pdf_visual_region_geometry import VisualRegion


def visual_region_sources_from_regions(
    *,
    page_no: int,
    regions: list[VisualRegion],
    full_page_quality_flags: list[str],
) -> list[ImageSource]:
    sources: list[ImageSource] = []
    for index, region in enumerate(regions, start=1):
        try:
            sources.append(
                normalized_image_source(
                    region.content,
                    filename=f"page-{page_no}-visual-region-{index}.png",
                    source_kind="pdf_scanned_visual_region",
                    quality_flags=sorted(
                        {
                            "source:pdf_page_image",
                            "source:visual_region_crop",
                            "scanned_mixed_page",
                            "visual_region_crop",
                            *region.quality_flags,
                            *full_page_quality_flags,
                        }
                    ),
                    page=page_no,
                    bbox=region.bbox,
                    target_content_type=PNG_CONTENT_TYPE,
                    page_area_ratio=region.page_area_ratio,
                )
            )
        except WorkerStepError:
            continue
    return sources
