"""Visual-region geometry, layout conversion, and crop materialization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
import math

from ..errors import WorkerStepError
from .image_normalization import bbox_area, bbox_from_value
from .layout import prepare_page_layout
from .models import BBox

LAYOUT_VISUAL_LABELS = {"figure", "image", "picture"}


@dataclass(frozen=True)
class VisualRegion:
    content: bytes
    bbox: BBox
    page_area_ratio: float
    quality_flags: tuple[str, ...] = ()


def visual_region_from_mask_bbox(
    rendered: object,
    *,
    mask_bbox: tuple[int, int, int, int],
    scale: float,
    page_width: float,
    page_height: float,
    quality_flags: tuple[str, ...] = (),
) -> VisualRegion | None:
    width, height = rendered.size
    left, top, right, bottom = mask_bbox
    crop_left = max(0, int(left / scale) - 4)
    crop_top = max(0, int(top / scale) - 4)
    crop_right = min(width, int(right / scale) + 4)
    crop_bottom = min(height, int(bottom / scale) + 4)
    return visual_region_from_pixel_bbox(
        rendered,
        pixel_bbox=(crop_left, crop_top, crop_right, crop_bottom),
        page_width=page_width,
        page_height=page_height,
        quality_flags=quality_flags,
    )


def layout_visual_regions_for_page(
    page: object,
    *,
    rendered: object,
    page_width: float,
    page_height: float,
    min_area_ratio: float,
    max_regions: int,
    prepare_page_layout_fn: Callable[
        [object], list[list[object]]
    ] = prepare_page_layout,
) -> list[VisualRegion]:
    if max_regions == 0:
        return []
    page_area = max(1.0, page_width * page_height)
    min_layout_area_ratio = max(0.005, min_area_ratio * 0.25)
    regions: list[VisualRegion] = []
    try:
        layout_rows = prepare_page_layout_fn(page)
    except WorkerStepError:
        return []
    for row in layout_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        label = str(row[4]).strip().lower()
        if label not in LAYOUT_VISUAL_LABELS:
            continue
        bbox = bbox_from_value(row[:4])
        if bbox is None:
            continue
        area_ratio = bbox_area(bbox) / page_area
        if area_ratio < min_layout_area_ratio:
            continue
        region = visual_region_from_pdf_bbox(
            rendered,
            pdf_bbox=bbox,
            page_width=page_width,
            page_height=page_height,
            quality_flags=("layout_model_region_crop",),
        )
        if region is not None:
            regions.append(region)
    regions.sort(
        key=lambda region: (region.bbox[1], region.bbox[0], -region.page_area_ratio)
    )
    return regions if max_regions < 0 else regions[:max_regions]


def visual_region_from_pdf_bbox(
    rendered: object,
    *,
    pdf_bbox: BBox,
    page_width: float,
    page_height: float,
    quality_flags: tuple[str, ...] = (),
) -> VisualRegion | None:
    width, height = rendered.size
    left, top, right, bottom = pdf_bbox
    pixel_bbox = (
        max(0, math.floor(left / page_width * width) - 8),
        max(0, math.floor(top / page_height * height) - 8),
        min(width, math.ceil(right / page_width * width) + 8),
        min(height, math.ceil(bottom / page_height * height) + 8),
    )
    return visual_region_from_pixel_bbox(
        rendered,
        pixel_bbox=pixel_bbox,
        page_width=page_width,
        page_height=page_height,
        quality_flags=quality_flags,
    )


def visual_region_from_pixel_bbox(
    rendered: object,
    *,
    pixel_bbox: tuple[int, int, int, int],
    page_width: float,
    page_height: float,
    quality_flags: tuple[str, ...] = (),
) -> VisualRegion | None:
    width, height = rendered.size
    crop_left, crop_top, crop_right, crop_bottom = pixel_bbox
    if crop_right <= crop_left or crop_bottom <= crop_top:
        return None
    crop = rendered.crop((crop_left, crop_top, crop_right, crop_bottom))
    output = BytesIO()
    crop.save(output, format="PNG")
    pdf_bbox = (
        crop_left / width * page_width,
        crop_top / height * page_height,
        crop_right / width * page_width,
        crop_bottom / height * page_height,
    )
    return VisualRegion(
        content=output.getvalue(),
        bbox=pdf_bbox,
        page_area_ratio=((pdf_bbox[2] - pdf_bbox[0]) * (pdf_bbox[3] - pdf_bbox[1]))
        / max(1.0, page_width * page_height),
        quality_flags=quality_flags,
    )


def visual_cue_context_regions(
    rendered: object,
    components: list[tuple[int, int, int, int, int]],
    *,
    visual_cue_bboxes: list[BBox],
    mask_size: tuple[int, int],
    scale: float,
    page_width: float,
    page_height: float,
    small_min_area_ratio: float,
    domain_visual_cue: bool,
) -> list[VisualRegion]:
    mask_width, mask_height = mask_size
    x_scale = mask_width / page_width
    y_scale = mask_height / page_height
    regions: list[VisualRegion] = []
    for cue_bbox in visual_cue_bboxes:
        cue_left = int(cue_bbox[0] * x_scale)
        cue_top = int(cue_bbox[1] * y_scale)
        cue_right = int(cue_bbox[2] * x_scale)
        cue_bottom = int(cue_bbox[3] * y_scale)
        search_box = (
            max(0, cue_left - int(mask_width * 0.45)),
            max(0, cue_top - int(mask_height * 0.38)),
            min(mask_width, cue_right + int(mask_width * 0.45)),
            min(mask_height, cue_bottom + int(mask_height * 0.45)),
        )
        candidates = [
            component
            for component in components
            if component_center_inside(component, search_box)
            and component_area_ratio(component, mask_width, mask_height)
            >= small_min_area_ratio * 0.4
        ]
        if not candidates:
            continue
        left = min(component[0] for component in candidates)
        top = min(component[1] for component in candidates)
        right = max(component[2] for component in candidates)
        bottom = max(component[3] for component in candidates)
        if ((right - left) * (bottom - top)) / max(1, mask_width * mask_height) > 0.5:
            continue
        flags = ("visual_cue_context_crop", "visual_cue_region_crop")
        if domain_visual_cue:
            flags = (*flags, "domain_visual_cue_crop")
        region = visual_region_from_mask_bbox(
            rendered,
            mask_bbox=(left, top, right, bottom),
            scale=scale,
            page_width=page_width,
            page_height=page_height,
            quality_flags=flags,
        )
        if region is not None:
            regions.append(region)
    return regions


def component_center_inside(
    component: tuple[int, int, int, int, int], bbox: tuple[int, int, int, int]
) -> bool:
    left, top, right, bottom, _ = component
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    return bbox[0] <= center_x <= bbox[2] and bbox[1] <= center_y <= bbox[3]


def component_area_ratio(
    component: tuple[int, int, int, int, int], width: int, height: int
) -> float:
    left, top, right, bottom, _ = component
    return ((right - left) * (bottom - top)) / max(1, width * height)


def region_overlap(a: BBox, b: BBox) -> float:
    left, top, right, bottom = (
        max(a[0], b[0]),
        max(a[1], b[1]),
        min(a[2], b[2]),
        min(a[3], b[3]),
    )
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    return overlap / max(1.0, min(bbox_area(a), bbox_area(b)))
