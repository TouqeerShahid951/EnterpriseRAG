"""Internal layout block model used before emitting parser items."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import BBox, ParsedPdfItem


@dataclass(frozen=True)
class FontMetrics:
    size: float | None = None
    bold: bool | None = None
    font_name: str | None = None


@dataclass(frozen=True)
class LayoutBlock:
    text: str
    role: str
    page_no: int | None
    bbox: BBox | None
    source: str
    confidence: float | None = None
    font_metrics: FontMetrics | None = None
    table_rows: list[list[str]] | None = None
    quality_flags: list[str] = field(default_factory=list)
    section_level: int | None = None
    table_json: dict[str, Any] | None = None


def blocks_to_items(blocks: list[LayoutBlock], *, parser: str) -> list[ParsedPdfItem]:
    return [
        ParsedPdfItem(
            index=index,
            text=block.text,
            item_type=_item_type(block.role),
            page_start=block.page_no,
            page_end=block.page_no,
            section_level=block.section_level,
            bbox=block.bbox,
            parser=parser,
            quality_flags=sorted(set(block.quality_flags)),
            table_json=block.table_json,
            confidence=block.confidence,
        )
        for index, block in enumerate(blocks)
        if block.text.strip()
    ]


def _item_type(role: str) -> str:
    normalized = role.strip().lower()
    if normalized in {"heading", "title", "section_header"}:
        return "heading"
    if normalized == "table":
        return "table"
    if normalized in {"figure", "picture", "caption"}:
        return normalized
    return "text"
