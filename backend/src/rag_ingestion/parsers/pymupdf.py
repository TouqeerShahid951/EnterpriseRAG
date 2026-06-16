"""PyMuPDF native PDF text extraction."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Callable

from ..errors import WorkerStepError
from .context import contextualized_item, is_boilerplate_text
from .models import ParsedPdfItem
from .reading_order import column_aware_reading_order
from .regions import LayoutEntry, layout_page_entries
from .tables import TableEntry, table_entries


@dataclass(frozen=True)
class PageEntry:
    y: float
    text: str
    item_type: str
    page_no: int
    bbox: tuple[float, float, float, float] | None = None
    quality_flags: list[str] | None = None
    table_json: dict[str, object] | None = None


@dataclass(frozen=True)
class PymuPDFParseResult:
    items: list[ParsedPdfItem]
    page_count: int
    page_text_chars: dict[int, int]
    page_quality_flags: dict[int, list[str]]


PageProgressCallback = Callable[[int, int], None]


def parse_pymupdf_pdf(file_bytes: bytes, *, page_progress_callback: PageProgressCallback | None = None) -> tuple[list[ParsedPdfItem], int]:
    result = parse_pymupdf_pdf_with_metadata(file_bytes, page_progress_callback=page_progress_callback)
    return result.items, result.page_count


def parse_pymupdf_pdf_with_metadata(file_bytes: bytes, *, page_progress_callback: PageProgressCallback | None = None) -> PymuPDFParseResult:
    try:
        import fitz
    except ImportError as exc:
        raise WorkerStepError("pdf_dependency_missing", "PyMuPDF dependency is not installed.") from exc

    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            return _document_items_with_metadata(document, page_progress_callback=page_progress_callback)
    except WorkerStepError:
        raise
    except Exception as exc:
        raise WorkerStepError("pdf_parse_failed", "PyMuPDF failed to parse PDF.") from exc


def _document_items(document: Any) -> list[ParsedPdfItem]:
    return _document_items_with_metadata(document).items


def _document_items_with_metadata(document: Any, *, page_progress_callback: PageProgressCallback | None = None) -> PymuPDFParseResult:
    parsed: list[ParsedPdfItem] = []
    current_section: str | None = None
    page_text_chars: dict[int, int] = {}
    page_quality_flags: dict[int, list[str]] = {}
    page_count = int(document.page_count)
    for page_index in range(page_count):
        page_no = page_index + 1
        page = document.load_page(page_index)
        page_text_chars[page_no] = _page_text_char_count(page)
        page_quality_flags[page_no] = _page_quality_flags(page)
        for entry in _page_entries(page, page_no):
            if is_boilerplate_text(entry.text):
                continue
            text, item_type = contextualized_item(entry.text, entry.item_type, current_section)
            if entry.item_type == "heading":
                current_section = entry.text
            parsed.append(
                ParsedPdfItem(
                    index=len(parsed),
                    text=text,
                    item_type=item_type,
                    page_start=page_no,
                    page_end=page_no,
                    section_title=entry.text if entry.item_type == "heading" else current_section,
                    bbox=entry.bbox,
                    quality_flags=sorted({*(entry.quality_flags or []), "source:pymupdf_native"}),
                    table_json=entry.table_json,
                )
            )
        if page_progress_callback:
            page_progress_callback(page_no, page_count)
    return PymuPDFParseResult(parsed, page_count, page_text_chars, page_quality_flags)


def _page_entries(page: Any, page_no: int) -> list[PageEntry]:
    tables = table_entries(page, page_no)
    layout_entries = layout_page_entries(page, page_no, tables)
    if layout_entries:
        return [_from_layout_entry(entry) for entry in layout_entries]
    table_boxes = [entry.bbox for entry in tables]
    text_entries = _text_entries(page, page_no, table_boxes)
    table_page_entries = [_table_page_entry(entry) for entry in tables]
    return column_aware_reading_order(
        [*text_entries, *table_page_entries],
        bbox_for=lambda item: item.bbox,
        page_width_value=_page_width(page),
    )


def _text_entries(page: Any, page_no: int, table_boxes: list[tuple[float, float, float, float]]) -> list[PageEntry]:
    blocks = [block for block in page.get_text("dict").get("blocks", []) if block.get("type") == 0]
    body_size = _body_font_size(blocks)
    entries: list[PageEntry] = []
    for block in blocks:
        bbox = tuple(float(value) for value in block.get("bbox", (0, 0, 0, 0)))
        if _inside_any_table(bbox, table_boxes):
            continue
        text = _block_text(block)
        if text and not is_boilerplate_text(text):
            entries.append(PageEntry(bbox[1], text, _block_type(block, text, body_size), page_no, bbox))
    return entries


def _block_text(block: dict[str, Any]) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        spans = [str(span.get("text", "")).strip() for span in line.get("spans", [])]
        line_text = " ".join(span for span in spans if span)
        if line_text:
            lines.append(line_text)
    return " ".join(" ".join(lines).split())


def _block_type(block: dict[str, Any], text: str, body_size: float) -> str:
    max_size = max(_span_sizes(block), default=0.0)
    bold = any("bold" in str(span.get("font", "")).lower() for line in block.get("lines", []) for span in line.get("spans", []))
    short = len(text) <= 140 and not text.endswith(".")
    if short and (max_size >= max(13.0, body_size + 1.25) or bold):
        return "heading"
    return "text"


def _body_font_size(blocks: list[dict[str, Any]]) -> float:
    sizes = [size for block in blocks for size in _span_sizes(block)]
    return float(median(sizes)) if sizes else 0.0


def _span_sizes(block: dict[str, Any]) -> list[float]:
    return [
        float(span.get("size", 0.0))
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if isinstance(span.get("size"), (int, float))
    ]


def _inside_any_table(bbox: tuple[float, float, float, float], table_boxes: list[tuple[float, float, float, float]]) -> bool:
    return any(_overlap_ratio(bbox, table_bbox) > 0.6 for table_bbox in table_boxes)


def _overlap_ratio(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left, top, right, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    area = max(1.0, (a[2] - a[0]) * (a[3] - a[1]))
    return ((right - left) * (bottom - top)) / area


def _table_page_entry(entry: TableEntry) -> PageEntry:
    quality_flags = ["structured_table_too_small"] if entry.row_count <= 1 else []
    return PageEntry(
        entry.bbox[1],
        entry.text,
        "table",
        entry.page_no,
        entry.bbox,
        quality_flags,
        {"rows": entry.rows, "row_count": entry.row_count},
    )


def _from_layout_entry(entry: LayoutEntry) -> PageEntry:
    return PageEntry(entry.y, entry.text, entry.item_type, entry.page_no, entry.bbox, entry.quality_flags, entry.table_json)


def _page_text_char_count(page: Any) -> int:
    get_text = getattr(page, "get_text", None)
    if get_text is None:
        return 0
    try:
        return len(" ".join(str(get_text("text")).split()))
    except Exception:
        return 0


def _page_quality_flags(page: Any) -> list[str]:
    flags: list[str] = []
    blocks = _page_blocks(page)
    text_blocks = [block for block in blocks if block.get("type") == 0]
    image_blocks = [block for block in blocks if block.get("type") == 1]
    text_chars = _text_chars_from_blocks(text_blocks)
    rotation = getattr(page, "rotation", 0)
    if isinstance(rotation, int) and rotation % 360:
        flags.append("rotated_page")
    if _has_rotated_text(text_blocks):
        flags.append("rotated_text")
    if image_blocks and not text_blocks:
        flags.append("image_only_page")
    if image_blocks and text_chars < 40:
        flags.append("scanned_or_handwritten_candidate")
    if _looks_multi_column(text_blocks, page):
        flags.append("multi_column_layout")
    if _looks_form_like(text_blocks):
        flags.append("form_like_layout")
    if _looks_invoice_like(text_blocks):
        flags.append("invoice_like_layout")
    return flags


def _page_blocks(page: Any) -> list[dict[str, Any]]:
    get_text = getattr(page, "get_text", None)
    if get_text is None:
        return []
    try:
        blocks = get_text("dict").get("blocks", [])
    except Exception:
        return []
    return [block for block in blocks if isinstance(block, dict)]


def _text_chars_from_blocks(blocks: list[dict[str, Any]]) -> int:
    return sum(len(_block_text(block)) for block in blocks)


def _has_rotated_text(blocks: list[dict[str, Any]]) -> bool:
    for block in blocks:
        for line in block.get("lines", []):
            direction = line.get("dir") if isinstance(line, dict) else None
            if not isinstance(direction, (list, tuple)) or len(direction) < 2:
                continue
            try:
                x_dir, y_dir = float(direction[0]), float(direction[1])
            except (TypeError, ValueError):
                continue
            if abs(y_dir) > 0.2 or x_dir < 0:
                return True
    return False


def _looks_multi_column(blocks: list[dict[str, Any]], page: Any) -> bool:
    text_blocks = [block for block in blocks if len(_block_text(block).split()) >= 3]
    if len(text_blocks) < 6:
        return False
    x_values = [float(block.get("bbox", (0, 0, 0, 0))[0]) for block in text_blocks]
    if len(set(round(value / 20) for value in x_values)) < 2:
        return False
    page_width = _page_width(page)
    if page_width <= 0:
        return False
    left = [value for value in x_values if value < page_width * 0.45]
    right = [value for value in x_values if value > page_width * 0.45]
    return len(left) >= 3 and len(right) >= 3 and (min(right) - min(left)) > page_width * 0.2


def _page_width(page: Any) -> float:
    rect = getattr(page, "rect", None)
    width = getattr(rect, "width", None)
    return float(width) if isinstance(width, (int, float)) else 0.0


def _looks_form_like(blocks: list[dict[str, Any]]) -> bool:
    texts = [_block_text(block) for block in blocks]
    short_texts = [text for text in texts if text and len(text) <= 80]
    key_value_count = sum(1 for text in short_texts if ":" in text or re_match_key_value(text))
    return len(short_texts) >= 6 and key_value_count >= 4


def re_match_key_value(text: str) -> bool:
    words = text.split()
    return 2 <= len(words) <= 8 and any(char.isdigit() for char in text) and any(char.isalpha() for char in text)


def _looks_invoice_like(blocks: list[dict[str, Any]]) -> bool:
    normalized = " ".join(_block_text(block).lower() for block in blocks)
    markers = ("invoice", "subtotal", "total", "amount due", "balance due", "tax", "qty", "quantity", "unit price")
    return sum(1 for marker in markers if marker in normalized) >= 3
