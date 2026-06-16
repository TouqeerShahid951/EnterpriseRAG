"""Weak page and region scoring for layered parser routing."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re

from .context import is_table_title
from .models import ParsedPdfItem

TABLE_FLAG_WEIGHTS = {
    "table_region_without_structured_rows": 3,
    "structured_table_too_small": 5,
    "collapsed_structured_table": 4,
    "flattened_table_text": 3,
    "table_chunk_without_markdown": 3,
    "table_structure_low_confidence": 3,
    "table_caption_without_structured_table": 4,
    "collapsed_measurement": 4,
}
PAGE_FLAG_WEIGHTS = {
    "image_only_page": 8,
    "scanned_or_handwritten_candidate": 8,
    "rotated_page": 5,
    "rotated_text": 5,
    "multi_column_layout": 5,
    "form_like_layout": 5,
    "invoice_like_layout": 5,
}
OCR_PAGE_FLAGS = {"image_only_page", "scanned_or_handwritten_candidate"}
LOW_COVERAGE_RATIO = 0.75
_COMPACT_MEASUREMENT_RE = re.compile(r"\b\d+\s*x\s*\d{2,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class WeakPage:
    page_no: int
    score: int
    flags: list[str]


def annotate_item_quality(
    items: list[ParsedPdfItem],
    page_text_chars: dict[int, int] | None = None,
    page_quality_flags: dict[int, list[str]] | None = None,
) -> list[ParsedPdfItem]:
    caption_flags = _table_caption_flags(items)
    coverage_flags = _coverage_flags(items, page_text_chars or {})
    page_flags = page_quality_flags or {}
    enriched: list[ParsedPdfItem] = []
    for item in items:
        flags = set(item.quality_flags)
        if item.item_type == "table" and not _looks_like_markdown_table(item.text):
            flags.add("table_chunk_without_markdown")
            flags.add("table_structure_low_confidence")
        if item.item_type == "table" and _COMPACT_MEASUREMENT_RE.search(item.text):
            flags.add("collapsed_measurement")
        if item.item_type != "heading" and not item.section_path:
            flags.add("orphan_text_without_section_path")
        for flag in caption_flags.get(item.index, []):
            flags.add(flag)
        for flag in coverage_flags.get(item.page_start or 0, []):
            flags.add(flag)
        for flag in page_flags.get(item.page_start or 0, []):
            flags.add(flag)
        enriched.append(replace(item, quality_flags=sorted(flags)))
    return enriched


def score_weak_pages(
    items: list[ParsedPdfItem],
    *,
    page_count: int,
    threshold: int,
    page_quality_flags: dict[int, list[str]] | None = None,
) -> list[WeakPage]:
    scores: dict[int, int] = {}
    flags_by_page: dict[int, set[str]] = {}
    for page_no, page_flags in (page_quality_flags or {}).items():
        for flag in page_flags:
            scores[page_no] = scores.get(page_no, 0) + PAGE_FLAG_WEIGHTS.get(flag, 0)
            flags_by_page.setdefault(page_no, set()).add(flag)
    for item in items:
        page_no = item.page_start
        if not page_no:
            continue
        page_flags = flags_by_page.setdefault(page_no, set())
        score = 0
        for flag in item.quality_flags:
            score += TABLE_FLAG_WEIGHTS.get(flag, PAGE_FLAG_WEIGHTS.get(flag, 3 if flag.startswith("low_parsed_text_coverage") else 0))
            page_flags.add(flag)
        scores[page_no] = scores.get(page_no, 0) + score
    return [
        WeakPage(page_no=page_no, score=scores.get(page_no, 0), flags=sorted(flags_by_page.get(page_no, set())))
        for page_no in range(1, page_count + 1)
        if scores.get(page_no, 0) >= threshold
    ]


def weak_page_ratio(weak_pages: list[WeakPage], page_count: int) -> float:
    return len(weak_pages) / max(1, page_count)


def ocr_candidate_pages(weak_pages: list[WeakPage]) -> set[int]:
    return {
        page.page_no
        for page in weak_pages
        if any(flag in OCR_PAGE_FLAGS for flag in page.flags)
    }


def _table_caption_flags(items: list[ParsedPdfItem]) -> dict[int, list[str]]:
    flags: dict[int, list[str]] = {}
    captions = [item for item in items if item.item_type == "heading" and is_table_title(item.text)]
    for caption in captions:
        has_structured_table = any(
            item.item_type == "table"
            and item.page_start == caption.page_start
            and item.section_title == caption.text
            and _looks_like_markdown_table(item.text)
            for item in items
        )
        if not has_structured_table:
            flags.setdefault(caption.index, []).append("table_caption_without_structured_table")
    return flags


def _coverage_flags(items: list[ParsedPdfItem], page_text_chars: dict[int, int]) -> dict[int, list[str]]:
    parsed_chars: dict[int, int] = {}
    for item in items:
        if item.page_start:
            parsed_chars[item.page_start] = parsed_chars.get(item.page_start, 0) + len(item.text)
    flags: dict[int, list[str]] = {}
    for page_no, raw_chars in page_text_chars.items():
        if raw_chars <= 0:
            continue
        ratio = parsed_chars.get(page_no, 0) / raw_chars
        if ratio < LOW_COVERAGE_RATIO:
            flags[page_no] = ["native_text_low_coverage", f"low_parsed_text_coverage:{ratio:.2f}"]
    return flags


def _looks_like_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return lines[0].startswith("|") and lines[0].endswith("|") and lines[1].startswith("|")
