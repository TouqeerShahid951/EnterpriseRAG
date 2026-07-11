"""PyMuPDF table extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TableEntry:
    text: str
    page_no: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def table_entries(page: Any, page_no: int) -> list[TableEntry]:
    if not hasattr(page, "find_tables"):
        return []
    finder = page.find_tables()
    entries: list[TableEntry] = []
    for table in getattr(finder, "tables", []) or []:
        rows = _clean_rows(table.extract())
        text = _markdown_table(rows)
        if text:
            entries.append(TableEntry(text=text, page_no=page_no, bbox=_bbox(table), rows=rows))
    return entries


def _clean_rows(raw_rows: list[list[Any]] | None) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_row in raw_rows or []:
        row = [str(cell or "").strip() for cell in raw_row]
        if any(row):
            rows.append(row)
    return rows


def _markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [_pad(row, width) for row in rows]
    header, body = normalized[0], normalized[1:]
    lines = [_markdown_row(header), _markdown_row(["---"] * width)]
    lines.extend(_markdown_row(row) for row in body)
    return "\n".join(lines)


def _pad(row: list[str], width: int) -> list[str]:
    return [*row, *([""] * (width - len(row)))]


def _markdown_row(row: list[str]) -> str:
    return "| " + " | ".join(_escape_cell(cell) for cell in row) + " |"


def _escape_cell(value: str) -> str:
    return " ".join(value.replace("|", "\\|").split())


def _bbox(table: Any) -> tuple[float, float, float, float]:
    values = getattr(table, "bbox", (0, 0, 0, 0))
    return tuple(float(value) for value in values)
