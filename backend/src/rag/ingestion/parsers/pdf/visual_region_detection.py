"""Detection of cropped visual regions on a rendered PDF page."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO

from rag.ingestion.errors import WorkerStepError
from rag.ingestion.parsers.layout import prepare_page_layout
from rag.ingestion.parsers.models import BBox
from rag.ingestion.parsers.pdf.visual_component_detection import connected_foreground_components
from rag.ingestion.parsers.pdf.visual_region_geometry import (
    VisualRegion,
    layout_visual_regions_for_page,
    region_overlap,
    visual_cue_context_regions,
    visual_region_from_mask_bbox,
)


def scanned_visual_regions_for_page(
    page: object,
    text_bboxes: list[BBox],
    *,
    visual_cue_bboxes: list[BBox],
    domain_visual_cue: bool,
    min_area_ratio: float,
    max_regions: int,
    text_mask_padding_px: int,
    prepare_page_layout_fn: Callable[
        [object], list[list[object]]
    ] = prepare_page_layout,
) -> tuple[list[VisualRegion], int, bool, int, int]:
    if max_regions == 0:
        return [], 0, False, 0, 0
    unlimited = max_regions < 0
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError as exc:
        raise WorkerStepError(
            "image_dependency_missing", "Pillow dependency is not installed."
        ) from exc

    pixmap = page.get_pixmap(dpi=150, alpha=False)
    rendered = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
    width, height = rendered.size
    page_rect = getattr(page, "rect", None)
    page_width = float(getattr(page_rect, "width", width) or width)
    page_height = float(getattr(page_rect, "height", height) or height)
    layout_regions = layout_visual_regions_for_page(
        page,
        rendered=rendered,
        page_width=page_width,
        page_height=page_height,
        min_area_ratio=min_area_ratio,
        max_regions=max_regions,
        prepare_page_layout_fn=prepare_page_layout_fn,
    )
    if layout_regions:
        return layout_regions, 0, False, 0, 0
    max_mask_dim = 640
    scale = min(1.0, max_mask_dim / max(width, height))
    mask_width = max(1, int(width * scale))
    mask_height = max(1, int(height * scale))
    grayscale = rendered.convert("L")
    if scale < 1.0:
        grayscale = grayscale.resize((mask_width, mask_height))
    mask = grayscale.point(lambda pixel: 255 if pixel < 245 else 0).filter(
        ImageFilter.MaxFilter(5)
    )
    draw = ImageDraw.Draw(mask)
    x_scale = mask_width / page_width
    y_scale = mask_height / page_height
    padding = int(text_mask_padding_px * scale)
    for bbox in text_bboxes:
        left = max(0, int(bbox[0] * x_scale) - padding)
        top = max(0, int(bbox[1] * y_scale) - padding)
        right = min(mask_width, int(bbox[2] * x_scale) + padding)
        bottom = min(mask_height, int(bbox[3] * y_scale) + padding)
        if right > left and bottom > top:
            draw.rectangle((left, top, right, bottom), fill=0)

    components = connected_foreground_components(mask)
    regions: list[VisualRegion] = []
    tiny_count = 0
    ambiguous = False
    cue_region_count = 0
    small_region_count = 0
    cue_mode = bool(visual_cue_bboxes)
    small_min_area_ratio = (
        min_area_ratio if not cue_mode else max(0.004, min_area_ratio * 0.18)
    )
    for left, top, right, bottom, foreground_pixels in components:
        bbox_area_ratio = ((right - left) * (bottom - top)) / max(
            1, mask_width * mask_height
        )
        if bbox_area_ratio > 0.85:
            ambiguous = True
            continue
        if bbox_area_ratio < small_min_area_ratio or foreground_pixels < 40:
            tiny_count += 1
            continue
        region_flags: tuple[str, ...] = ()
        if bbox_area_ratio < min_area_ratio:
            region_flags = ("small_visual_region_crop", "visual_cue_region_crop")
            if domain_visual_cue:
                region_flags = (*region_flags, "domain_visual_cue_crop")
            small_region_count += 1
        region = visual_region_from_mask_bbox(
            rendered,
            mask_bbox=(left, top, right, bottom),
            scale=scale,
            page_width=page_width,
            page_height=page_height,
            quality_flags=region_flags,
        )
        if region is None:
            tiny_count += 1
            continue
        regions.append(region)

    if cue_mode and (unlimited or len(regions) < max_regions):
        context_regions = visual_cue_context_regions(
            rendered,
            components,
            visual_cue_bboxes=visual_cue_bboxes,
            mask_size=(mask_width, mask_height),
            scale=scale,
            page_width=page_width,
            page_height=page_height,
            small_min_area_ratio=small_min_area_ratio,
            domain_visual_cue=domain_visual_cue,
        )
        for region in context_regions:
            if any(
                region_overlap(region.bbox, existing.bbox) > 0.65
                for existing in regions
            ):
                continue
            regions.append(region)
            cue_region_count += 1
            if not unlimited and len(regions) >= max_regions:
                break
    regions.sort(
        key=lambda region: (
            0 if "visual_cue_context_crop" in region.quality_flags else 1,
            -region.page_area_ratio,
        )
    )
    return (
        (regions if unlimited else regions[:max_regions]),
        tiny_count,
        ambiguous,
        cue_region_count,
        small_region_count,
    )
