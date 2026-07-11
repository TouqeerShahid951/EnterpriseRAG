"""Metadata helpers for parsed PDF item groups."""

from __future__ import annotations

from ..parsers.models import ParsedPdfItem


def section_text(items: list[ParsedPdfItem]) -> str:
    return "\n\n".join(item.text for item in items if item.text).strip()


def page_start(items: list[ParsedPdfItem]) -> int | None:
    pages = [item.page_start for item in items if item.page_start]
    return min(pages) if pages else None


def page_end(items: list[ParsedPdfItem]) -> int | None:
    pages = [item.page_end or item.page_start for item in items if item.page_end or item.page_start]
    return max(pages) if pages else None


def section_title(items: list[ParsedPdfItem]) -> str | None:
    return next((item.section_title for item in items if item.section_title), None)


def section_path(items: list[ParsedPdfItem]) -> list[str]:
    return next((item.section_path for item in items if item.section_path), [])


def parent_section_id(items: list[ParsedPdfItem]) -> str | None:
    return next((item.parent_section_id for item in items if item.parent_section_id), None)


def parser_name(items: list[ParsedPdfItem]) -> str:
    names = {item.parser for item in items if item.parser}
    return names.pop() if len(names) == 1 else "mixed"


def quality_flags(items: list[ParsedPdfItem]) -> list[str]:
    return sorted({flag for item in items for flag in item.quality_flags})


def table_json(items: list[ParsedPdfItem]) -> dict[str, object] | None:
    return next((item.table_json for item in items if item.table_json), None)


def source_regions(items: list[ParsedPdfItem]) -> list[dict[str, object]]:
    regions: list[dict[str, object]] = []
    for item in items:
        if item.bbox is None and not item.image_asset_id:
            continue
        region: dict[str, object] = {
            "page": item.page_start,
            "bbox": [float(value) for value in item.bbox] if item.bbox is not None else None,
            "text": item.text,
            "region_type": item.item_type,
            "confidence": item.confidence,
        }
        if item.image_asset_id:
            region["image_asset_id"] = item.image_asset_id
        if item.image_source_kind:
            region["image_source_kind"] = item.image_source_kind
        if item.extraction_method:
            region["extraction_method"] = item.extraction_method
        regions.append(region)
    return regions


def merge_item(items: list[ParsedPdfItem]) -> ParsedPdfItem:
    return ParsedPdfItem(
        index=items[0].index,
        text=section_text(items),
        item_type="text",
        page_start=page_start(items),
        page_end=page_end(items),
        section_title=section_title(items),
        section_path=section_path(items),
        parent_section_id=parent_section_id(items),
        parser=parser_name(items),
        quality_flags=quality_flags(items),
        table_json=table_json(items),
        image_asset_id=next((item.image_asset_id for item in items if item.image_asset_id), None),
        image_source_kind=next((item.image_source_kind for item in items if item.image_source_kind), None),
        image_content_type=next((item.image_content_type for item in items if item.image_content_type), None),
        extraction_method=next((item.extraction_method for item in items if item.extraction_method), None),
    )
