"""Layout-region extraction for PyMuPDF pages."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .context import is_boilerplate_text, is_table_title
from .layout import prepare_page_layout
from .reading_order import column_aware_reading_order, page_width
from .tables import TableEntry

SKIPPED_LABELS = {"page-footer", "page-header", "footer", "header"}
HEADING_LABELS = {"section-header", "title", "heading"}


@dataclass(frozen=True)
class LayoutRegion:
    bbox: tuple[float, float, float, float]
    label: str

    @property
    def x(self) -> float:
        return self.bbox[0]

    @property
    def y(self) -> float:
        return self.bbox[1]


@dataclass(frozen=True)
class LayoutEntry:
    y: float
    text: str
    item_type: str
    page_no: int
    table_id: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    quality_flags: list[str] | None = None
    table_json: dict[str, object] | None = None


def layout_page_entries(page: Any, page_no: int, tables: list[TableEntry]) -> list[LayoutEntry]:
    regions = _layout_regions(page)
    if not regions:
        return []
    entries: list[LayoutEntry] = []
    used_table_ids: set[int] = set()
    page_width_value = page_width(page)
    for region in column_aware_reading_order(regions, bbox_for=lambda item: item.bbox, page_width_value=page_width_value):
        if region.label in SKIPPED_LABELS:
            continue
        entry = _entry_for_region(page, page_no, region, tables)
        if entry and not is_boilerplate_text(entry.text):
            entries.append(entry)
            if entry.table_id is not None:
                used_table_ids.add(entry.table_id)
    entries.extend(_unmatched_table_entries(tables, used_table_ids))
    return column_aware_reading_order(entries, bbox_for=lambda item: item.bbox, page_width_value=page_width_value)


def _layout_regions(page: Any) -> list[LayoutRegion]:
    regions: list[LayoutRegion] = []
    for row in prepare_page_layout(page):
        region = _coerce_region(row)
        if region is not None:
            regions.append(region)
    return regions


def _coerce_region(row: Any) -> LayoutRegion | None:
    if not isinstance(row, (list, tuple)) or len(row) < 5:
        return None
    try:
        bbox = tuple(float(value) for value in row[:4])
    except (TypeError, ValueError):
        return None
    label = str(row[4]).strip().lower()
    if not label or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return LayoutRegion(bbox=bbox, label=label)


def _entry_for_region(
    page: Any,
    page_no: int,
    region: LayoutRegion,
    tables: list[TableEntry],
) -> LayoutEntry | None:
    table_id, table = _matching_table(region, tables)
    region_text = _region_text(page, region)
    table_text = table.text if table else None
    quality_flags: list[str] = []
    table_json: dict[str, object] | None = None
    if region.label == "table":
        text, quality_flags = table_text_choice(region_text, table_text, table.row_count if table else 0)
        if table is not None:
            table_json = {"rows": table.rows, "row_count": table.row_count}
    else:
        text = region_text
    if not text:
        return None
    return LayoutEntry(
        y=region.y,
        text=text,
        item_type=_item_type(region.label, text),
        page_no=page_no,
        table_id=table_id if region.label == "table" else None,
        bbox=region.bbox,
        quality_flags=quality_flags,
        table_json=table_json,
    )


def _region_text(page: Any, region: LayoutRegion) -> str:
    get_textbox = getattr(page, "get_textbox", None)
    if get_textbox is None:
        return ""
    return " ".join(str(get_textbox(region.bbox)).split())


def _item_type(label: str, text: str) -> str:
    if label == "table":
        return "table"
    if label in HEADING_LABELS or is_table_title(text):
        return "heading"
    return "text"


def _matching_table(region: LayoutRegion, tables: list[TableEntry]) -> tuple[int | None, TableEntry | None]:
    matches = [
        (index, table, overlap_ratio(region.bbox, table.bbox))
        for index, table in enumerate(tables)
    ]
    matches.sort(key=lambda item: item[2], reverse=True)
    if matches and matches[0][2] >= 0.2:
        return matches[0][0], matches[0][1]
    return None, None


def _unmatched_table_entries(tables: list[TableEntry], used_table_ids: set[int]) -> list[LayoutEntry]:
    return [
        LayoutEntry(
            entry.bbox[1],
            entry.text,
            "table",
            entry.page_no,
            index,
            entry.bbox,
            _structured_table_flags(entry.text, entry.row_count),
            {"rows": entry.rows, "row_count": entry.row_count},
        )
        for index, entry in enumerate(tables)
        if index not in used_table_ids
    ]


def table_text_choice(region_text: str, structured_text: str | None, structured_row_count: int) -> tuple[str, list[str]]:
    flags: list[str] = []
    if not structured_text:
        flags.append("table_region_without_structured_rows")
        if region_text and not _looks_like_markdown_table(region_text):
            flags.append("flattened_table_text")
        return region_text, flags
    if region_text and _has_collapsed_phrases(structured_text, region_text):
        flags.append("collapsed_structured_table")
        if not _looks_like_markdown_table(region_text):
            flags.append("flattened_table_text")
        return region_text, flags
    if _word_count(structured_text) >= max(8, int(_word_count(region_text) * 0.75)):
        return structured_text, _structured_table_flags(structured_text, structured_row_count)
    flags.append("structured_table_too_small")
    if region_text and not _looks_like_markdown_table(region_text):
        flags.append("flattened_table_text")
    return region_text or structured_text, flags


def _structured_table_flags(text: str, row_count: int) -> list[str]:
    flags: list[str] = []
    if row_count <= 1:
        flags.append("structured_table_too_small")
        flags.append("table_structure_low_confidence")
    if text and not _looks_like_markdown_table(text):
        flags.append("flattened_table_text")
        flags.append("table_structure_low_confidence")
    return flags


def _looks_like_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return lines[0].startswith("|") and lines[0].endswith("|") and lines[1].startswith("|")


def overlap_ratio(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left, top, right, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    return overlap / max(1.0, min(_area(a), _area(b)))


def _has_collapsed_phrases(structured_text: str, region_text: str) -> bool:
    normalized_structured = _normalized(structured_text)
    compact_structured = re.sub(r"[^a-z0-9]+", "", normalized_structured)
    structured_words = {_clean_word(word) for word in structured_text.split()}
    collapsed_count = 0
    words = [clean for clean in (_clean_word(word) for word in region_text.split()) if clean]
    for left, right in zip(words, words[1:]):
        if not _phrase_candidate(left, right):
            continue
        if left in structured_words and right in structured_words:
            continue
        phrase = f"{left} {right}"
        if phrase not in normalized_structured and f"{left}{right}" in compact_structured:
            collapsed_count += 1
    return collapsed_count >= 2


def _phrase_candidate(left: str, right: str) -> bool:
    return left.isalpha() and right.isalpha() and len(left) >= 3 and len(right) >= 3


def _clean_word(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", word.lower())


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _word_count(text: str) -> int:
    return len(text.split())


def _area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
