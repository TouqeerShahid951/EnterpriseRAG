"""Detection and cropping of visual regions on scanned PDF pages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
import math
import re

from ..errors import WorkerStepError
from .image_contracts import ImageSource, PNG_CONTENT_TYPE, ScannedVisualRegionResult
from .image_normalization import bbox_area, bbox_from_value, normalized_image_source
from .image_sources import fitz_module
from .layout import prepare_page_layout
from .models import BBox, ParsedPdfItem

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
LAYOUT_VISUAL_LABELS = {"figure", "image", "picture"}


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


@dataclass(frozen=True)
class VisualRegion:
    content: bytes
    bbox: BBox
    page_area_ratio: float
    quality_flags: tuple[str, ...] = ()


def scanned_visual_regions_for_page(
    page: object,
    text_bboxes: list[BBox],
    *,
    visual_cue_bboxes: list[BBox],
    domain_visual_cue: bool,
    min_area_ratio: float,
    max_regions: int,
    text_mask_padding_px: int,
    prepare_page_layout_fn: Callable[[object], list[list[object]]] = prepare_page_layout,
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
    prepare_page_layout_fn: Callable[[object], list[list[object]]] = prepare_page_layout,
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


def connected_foreground_components(
    mask: object,
) -> list[tuple[int, int, int, int, int]]:
    width, height = mask.size
    data = mask.tobytes()
    visited = bytearray(len(data))
    components: list[tuple[int, int, int, int, int]] = []
    for index, value in enumerate(data):
        if value == 0 or visited[index]:
            continue
        stack = [index]
        visited[index] = 1
        min_x = max_x = index % width
        min_y = max_y = index // width
        count = 0
        while stack:
            current = stack.pop()
            count += 1
            x = current % width
            y = current // width
            if x < min_x:
                min_x = x
            elif x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            elif y > max_y:
                max_y = y
            for neighbor in foreground_neighbors(current, x, y, width, height):
                if not visited[neighbor] and data[neighbor] != 0:
                    visited[neighbor] = 1
                    stack.append(neighbor)
        components.append((min_x, min_y, max_x + 1, max_y + 1, count))
    return components


def foreground_neighbors(
    index: int, x: int, y: int, width: int, height: int
) -> tuple[int, ...]:
    neighbors: list[int] = []
    if x > 0:
        neighbors.append(index - 1)
    if x + 1 < width:
        neighbors.append(index + 1)
    if y > 0:
        neighbors.append(index - width)
    if y + 1 < height:
        neighbors.append(index + width)
    return tuple(neighbors)


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
