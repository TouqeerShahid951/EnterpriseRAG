"""Consolidate duplicate PDF OCR blocks into their source image transcription."""

from dataclasses import replace
import math
import re

from ..images.analysis import image_item_description
from ..models import BBox, ParsedPdfItem


def consolidate_image_ocr(
    parsed_items: list[ParsedPdfItem], image_items: list[ParsedPdfItem]
) -> tuple[list[ParsedPdfItem], list[ParsedPdfItem]]:
    by_page: dict[int, list[tuple[int, ParsedPdfItem]]] = {}
    for index, item in enumerate(parsed_items):
        if (
            item.item_type not in {"text", "caption"}
            or item.table_json is not None
            or item.image_asset_id is not None
            or "source:ocr" not in item.quality_flags
            or not item.text.strip()
            or item.page_start is None
            or item.page_end not in {None, item.page_start}
            or not _valid_bbox(item.bbox)
        ):
            continue
        by_page.setdefault(item.page_start, []).append((index, item))

    consumed: set[int] = set()
    images = list(image_items)
    # ponytail: exact text and full containment only; uncertain alternatives stay reviewable.
    for image_index, image in enumerate(images):
        if (
            not image.image_asset_id
            or not (image.image_source_kind or "").startswith("pdf")
            or image.page_start is None
            or image.page_end not in {None, image.page_start}
            or not _valid_bbox(image.bbox)
            or "source:ocr" not in image.quality_flags
            or image_item_description(image) is None
        ):
            continue
        transcription = image.quote_texts[0]
        used_ranges: list[tuple[int, int]] = []
        duplicates: list[ParsedPdfItem] = []
        spans = list(image.source_spans)
        for index, item in by_page.get(image.page_start, []):
            if index in consumed or not _contains(image.bbox, item.bbox):
                continue
            source_spans = item.source_spans or [
                {
                    "page": item.page_start,
                    "bbox": list(item.bbox),
                    "exact_text": item.text,
                }
            ]
            if any(
                span["page"] != image.page_start
                or not _valid_bbox(span["bbox"])
                or not _contains(image.bbox, span["bbox"])
                for span in source_spans
            ):
                continue
            pattern = (
                r"(?<!\S)"
                + r"\s+".join(re.escape(word) for word in item.text.split())
                + r"(?!\S)"
            )
            match = next(
                (
                    match
                    for match in re.finditer(pattern, transcription)
                    if not any(
                        match.start() < end and start < match.end()
                        for start, end in used_ranges
                    )
                ),
                None,
            )
            if match is None:
                continue
            used_ranges.append(match.span())
            consumed.add(index)
            duplicates.append(item)
            for span in source_spans:
                if span not in spans:
                    spans.append(span)
        if duplicates:
            confidences = [item.confidence for item in [image, *duplicates]]
            images[image_index] = replace(
                image,
                confidence=None if None in confidences else min(confidences),
                source_spans=spans,
                quality_flags=sorted(
                    {
                        *image.quality_flags,
                        "ocr_image_consolidated",
                        *(flag for item in duplicates for flag in item.quality_flags),
                    }
                ),
            )
    return [
        item for index, item in enumerate(parsed_items) if index not in consumed
    ], images


def _valid_bbox(bbox: BBox | None) -> bool:
    return bool(
        bbox is not None
        and len(bbox) == 4
        and all(math.isfinite(value) for value in bbox)
        and bbox[0] < bbox[2]
        and bbox[1] < bbox[3]
    )


def _contains(outer: BBox, inner: BBox) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )
