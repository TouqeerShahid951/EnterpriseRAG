"""Docling repair merging for the layered PDF parser."""

from __future__ import annotations

from dataclasses import replace
import re

from rag.ingestion.parsers.models import BBox, ParsedPdfItem
from rag.ingestion.parsers.quality import WeakPage

WHOLE_PAGE_REPAIR_FLAGS = {
    "image_only_page",
    "scanned_or_handwritten_candidate",
    "rotated_page",
    "invoice_like_layout",
}


def merge_docling_repairs(
    baseline_items: list[ParsedPdfItem],
    docling_items: list[ParsedPdfItem],
    weak_pages: list[WeakPage],
) -> list[ParsedPdfItem]:
    weak_page_numbers = {page.page_no for page in weak_pages}
    weak_page_by_number = {page.page_no: page for page in weak_pages}
    page_repairs = _page_repairs(docling_items)
    used_docling_ids: set[int] = set()
    repaired_whole_pages: set[int] = set()
    merged: list[ParsedPdfItem] = []
    for item in baseline_items:
        page_no = item.page_start
        if page_no in weak_page_numbers and _needs_whole_page_repair(weak_page_by_number[page_no]):
            repairs = page_repairs.get(page_no, [])
            if repairs:
                repair_indexes = {index for index, _repair in repairs}
                if not repair_indexes & used_docling_ids:
                    merged.extend(_inherit_page_context([repair for _index, repair in repairs], item))
                    used_docling_ids.update(repair_indexes)
                    repaired_whole_pages.add(page_no)
                continue
            merged.append(_with_flag(item, "docling_page_repair_unavailable"))
            continue
        if item.item_type != "table" or page_no not in weak_page_numbers:
            merged.append(item)
            continue
        match_index, repair = _best_docling_match(item, docling_items, used_docling_ids)
        if repair is None:
            merged.append(_with_flag(item, "docling_repair_unavailable"))
            continue
        used_docling_ids.add(match_index)
        merged.append(_repair_item(item, repair))
    for page_no, weak_page in weak_page_by_number.items():
        if page_no in repaired_whole_pages or not _needs_whole_page_repair(weak_page):
            continue
        repairs = page_repairs.get(page_no, [])
        if repairs:
            merged.extend(repair for _index, repair in repairs)
    return _renumber_items(merged)


def _best_docling_match(
    item: ParsedPdfItem,
    repairs: list[ParsedPdfItem],
    used_docling_ids: set[int],
) -> tuple[int, ParsedPdfItem | None]:
    best_index = -1
    best_item: ParsedPdfItem | None = None
    best_score = 0.0
    for index, repair in enumerate(repairs):
        if index in used_docling_ids or repair.item_type != "table":
            continue
        if item.page_start and repair.page_start and item.page_start != repair.page_start:
            continue
        score = max(_bbox_overlap(item.bbox, repair.bbox), _text_similarity(item.text, repair.text))
        if score > best_score:
            best_index, best_item, best_score = index, repair, score
    return (best_index, best_item) if best_score >= 0.08 else (-1, None)


def _repair_item(item: ParsedPdfItem, repair: ParsedPdfItem) -> ParsedPdfItem:
    flags = sorted({*item.quality_flags, *repair.quality_flags, "docling_repaired"})
    return replace(
        item,
        text=repair.text,
        parser="docling",
        quality_flags=flags,
        table_json=repair.table_json,
        bbox=repair.bbox or item.bbox,
    )


def _needs_whole_page_repair(weak_page: WeakPage) -> bool:
    return any(flag in WHOLE_PAGE_REPAIR_FLAGS for flag in weak_page.flags)


def _page_repairs(items: list[ParsedPdfItem]) -> dict[int, list[tuple[int, ParsedPdfItem]]]:
    grouped: dict[int, list[tuple[int, ParsedPdfItem]]] = {}
    for index, item in enumerate(items):
        if item.page_start is None:
            continue
        grouped.setdefault(item.page_start, []).append((index, item))
    return grouped


def _inherit_page_context(items: list[ParsedPdfItem], source: ParsedPdfItem) -> list[ParsedPdfItem]:
    return [
        replace(
            item,
            section_title=item.section_title or source.section_title,
            section_path=item.section_path or source.section_path,
            section_level=item.section_level if item.section_level is not None else source.section_level,
            parent_section_id=item.parent_section_id or source.parent_section_id,
        )
        for item in items
    ]


def _renumber_items(items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    return [replace(item, index=index) for index, item in enumerate(items)]


def _with_flag(item: ParsedPdfItem, flag: str) -> ParsedPdfItem:
    return replace(item, quality_flags=sorted({*item.quality_flags, flag}))


def _bbox_overlap(a: BBox | None, b: BBox | None) -> float:
    if a is None or b is None:
        return 0.0
    left, top, right, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    area = max(1.0, min(_area(a), _area(b)))
    return overlap / area


def _area(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _text_similarity(a: str, b: str) -> float:
    left = _tokens(a)
    right = _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}
