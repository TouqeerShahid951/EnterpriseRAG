"""Structure-aware chunking for parsed PDF items."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..parsers.context import is_table_title
from ..parsers.models import ParsedPdfItem
from .meta import merge_item, page_end, page_start, parent_section_id, parser_name, quality_flags, section_path, section_text, section_title, source_regions, table_json
from .tables import TableRow, form_like_record_chunks, table_chunks
from .text import CHARS_PER_TOKEN_GUARD, _token_count, _too_large, split_text

LOW_CONFIDENCE_OCR_TABLE_THRESHOLD = 0.9


@dataclass(frozen=True)
class TextChunk:
    index: int
    page: int | None
    text: str
    parent_chunk_id: str
    parent_text: str
    chunk_type: str
    section_title: str | None
    page_start: int | None
    page_end: int | None
    section_path: list[str] = field(default_factory=list)
    parent_section_id: str | None = None
    parser: str = "pymupdf"
    quality_flags: list[str] = field(default_factory=list)
    table_json: dict[str, object] | None = None
    parent_page_start: int | None = None
    parent_page_end: int | None = None
    table_title: str = ""
    table_caption: str = ""
    table_row_label: str = ""
    table_column_headers: list[str] = field(default_factory=list)
    table_row_index: int | None = None
    structured_kind: str = ""
    structured_fields: list[dict[str, str]] = field(default_factory=list)
    structured_field_names: list[str] = field(default_factory=list)
    structured_field_values: list[str] = field(default_factory=list)
    structured_search_text: str = ""
    source_regions: list[dict[str, object]] = field(default_factory=list)


def chunk_items(
    items: list[ParsedPdfItem],
    *,
    doc_id: str,
    target_tokens: int,
    overlap_tokens: int,
    parent_max_tokens: int,
) -> list[TextChunk]:
    _validate_settings(target_tokens, overlap_tokens, parent_max_tokens)
    chunks: list[TextChunk] = []
    vision_ocr_pages = _vision_ocr_pages(items)
    for parent_index, section in enumerate(_parent_sections(items, parent_max_tokens)):
        parent_id = f"{doc_id}:parent:{parent_index}"
        parent_text = section_text(section)
        parent_start = page_start(section)
        parent_end = page_end(section)
        for row in _child_texts(section, target_tokens, overlap_tokens, vision_ocr_pages=vision_ocr_pages):
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    page=row.page_start,
                    text=row.text,
                    parent_chunk_id=parent_id,
                    parent_text=parent_text,
                    chunk_type=row.chunk_type,
                    section_title=row.section_title,
                    page_start=row.page_start,
                    page_end=row.page_end,
                    section_path=row.section_path,
                    parent_section_id=row.parent_section_id,
                    parser=row.parser,
                    quality_flags=row.quality_flags,
                    table_json=row.table_json,
                    parent_page_start=parent_start,
                    parent_page_end=parent_end,
                    table_title=row.table_title,
                    table_caption=row.table_caption,
                    table_row_label=row.table_row_label,
                    table_column_headers=row.table_column_headers,
                    table_row_index=row.table_row_index,
                    structured_kind=row.structured_kind,
                    structured_fields=row.structured_fields,
                    structured_field_names=row.structured_field_names,
                    structured_field_values=row.structured_field_values,
                    structured_search_text=row.structured_search_text,
                    source_regions=row.source_regions,
                )
            )
    return chunks


def _validate_settings(target_tokens: int, overlap_tokens: int, parent_max_tokens: int) -> None:
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than target_tokens")
    if parent_max_tokens < target_tokens:
        raise ValueError("parent_max_tokens must be at least target_tokens")


def _parent_sections(items: list[ParsedPdfItem], parent_max_tokens: int) -> list[list[ParsedPdfItem]]:
    sections: list[list[ParsedPdfItem]] = []
    current: list[ParsedPdfItem] = []
    for item in items:
        starts_section = item.item_type == "heading" and current
        exceeds_parent = current and _token_count(section_text([*current, item])) > parent_max_tokens
        if starts_section or exceeds_parent:
            sections.append(current)
            current = []
        current.append(item)
    if current:
        sections.append(current)
    return sections


def _child_texts(
    section: list[ParsedPdfItem],
    target_tokens: int,
    overlap_tokens: int,
    *,
    vision_ocr_pages: set[int],
) -> list[TableRow]:
    rows: list[TableRow] = []
    text_items: list[ParsedPdfItem] = []
    for item in section:
        if item.item_type == "table":
            table_title_hint = _nearest_table_title(text_items)
            rows.extend(_flush_text_items(text_items, target_tokens, overlap_tokens))
            text_items = []
            rows.extend(
                table_chunks(
                    item,
                    target_tokens,
                    table_title_hint=table_title_hint,
                    include_row_chunks=not _prefer_page_vision_ocr_for_table(item, vision_ocr_pages),
                )
            )
        else:
            text_items.append(item)
    rows.extend(_flush_text_items(text_items, target_tokens, overlap_tokens))
    return rows


def _vision_ocr_pages(items: list[ParsedPdfItem]) -> set[int]:
    pages: set[int] = set()
    for item in items:
        flags = set(item.quality_flags)
        if item.item_type != "image_text" or "source:vision" not in flags or "source:ocr" not in flags:
            continue
        if not item.text.strip():
            continue
        pages.update(_item_pages(item))
    return pages


def _prefer_page_vision_ocr_for_table(item: ParsedPdfItem, vision_ocr_pages: set[int]) -> bool:
    if item.item_type != "table" or "source:vision" in item.quality_flags:
        return False
    if not any(page in vision_ocr_pages for page in _item_pages(item)):
        return False
    flags = set(item.quality_flags)
    if "source:ocr" not in flags:
        return False
    if not (item.parser == "docling" or "source:docling_layout" in flags or "docling_ocr" in flags):
        return False
    return item.confidence is None or item.confidence < LOW_CONFIDENCE_OCR_TABLE_THRESHOLD


def _item_pages(item: ParsedPdfItem) -> range:
    if item.page_start is None:
        return range(0)
    page_end_value = item.page_end or item.page_start
    if page_end_value < item.page_start:
        return range(0)
    return range(item.page_start, page_end_value + 1)


def _nearest_table_title(items: list[ParsedPdfItem]) -> str:
    for item in reversed(items):
        for line in reversed(item.text.splitlines()):
            candidate = line.strip()
            if is_table_title(candidate):
                return candidate
    return ""


def _flush_text_items(
    items: list[ParsedPdfItem],
    target_tokens: int,
    overlap_tokens: int,
) -> list[TableRow]:
    rows: list[TableRow] = []
    current_text_items: list[ParsedPdfItem] = []
    current_form_items: list[ParsedPdfItem] = []

    def flush_text_items() -> None:
        nonlocal current_text_items
        rows.extend(_flush_plain_text_items(current_text_items, target_tokens, overlap_tokens))
        current_text_items = []

    def flush_form_items() -> None:
        nonlocal current_form_items
        if not current_form_items:
            return
        structured_rows = form_like_record_chunks(current_form_items, target_tokens)
        if structured_rows:
            rows.extend(structured_rows)
        else:
            rows.extend(_flush_plain_text_items(current_form_items, target_tokens, overlap_tokens))
        current_form_items = []

    for item in items:
        if _is_form_like_item(item):
            if current_text_items:
                flush_text_items()
            if current_form_items and not _same_form_group(current_form_items[-1], item):
                flush_form_items()
            current_form_items.append(item)
            continue
        if current_form_items:
            flush_form_items()
        current_text_items.append(item)

    if current_form_items:
        flush_form_items()
    if current_text_items:
        flush_text_items()
    return rows


def _flush_plain_text_items(
    items: list[ParsedPdfItem],
    target_tokens: int,
    overlap_tokens: int,
) -> list[TableRow]:
    rows: list[TableRow] = []
    current: list[ParsedPdfItem] = []
    for item in items:
        if _token_count(item.text) > target_tokens:
            rows.extend(_emit_text(current, target_tokens, overlap_tokens))
            current = []
            rows.extend(_split_long_item(item, target_tokens, overlap_tokens))
        elif current and _token_count(section_text([*current, item])) > target_tokens:
            rows.extend(_emit_text(current, target_tokens, overlap_tokens))
            current = [item]
        else:
            current.append(item)
    rows.extend(_emit_text(current, target_tokens, overlap_tokens))
    return rows


def _is_form_like_item(item: ParsedPdfItem) -> bool:
    return "form_like_layout" in item.quality_flags and item.item_type == "text"


def _same_form_group(left: ParsedPdfItem, right: ParsedPdfItem) -> bool:
    return (
        left.page_start == right.page_start
        and left.page_end == right.page_end
        and left.section_title == right.section_title
        and left.parent_section_id == right.parent_section_id
    )


def _emit_text(
    items: list[ParsedPdfItem],
    target_tokens: int,
    overlap_tokens: int,
) -> list[TableRow]:
    if not items:
        return []
    text = section_text(items)
    if not _too_large(text, target_tokens, target_tokens * CHARS_PER_TOKEN_GUARD):
        return [
            TableRow(
                text=text,
                chunk_type="text",
                page_start=page_start(items),
                page_end=page_end(items),
                section_title=section_title(items),
                section_path=section_path(items),
                parent_section_id=parent_section_id(items),
                parser=parser_name(items),
                quality_flags=quality_flags(items),
                table_json=table_json(items),
                source_regions=source_regions(items),
            )
        ]
    return _split_long_item(merge_item(items), target_tokens, overlap_tokens)


def _split_long_item(
    item: ParsedPdfItem,
    target_tokens: int,
    overlap_tokens: int,
) -> list[TableRow]:
    return [
        TableRow(
            text=piece,
            chunk_type=item.item_type if item.item_type == "heading" else "text",
            page_start=item.page_start,
            page_end=item.page_end,
            section_title=item.section_title,
            section_path=item.section_path,
            parent_section_id=item.parent_section_id,
            parser=item.parser,
            quality_flags=item.quality_flags,
            table_json=item.table_json,
            source_regions=source_regions([item]),
        )
        for piece in split_text(item.text, target_tokens=target_tokens, overlap_tokens=overlap_tokens)
    ]
