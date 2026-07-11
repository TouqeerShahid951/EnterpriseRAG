"""Table-preserving chunk helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from rag.shared.contracts.structured_payloads import (
    canonical_structured_search_text,
    collapse_whitespace,
    normalized_field_names,
    normalized_field_values,
)

from ..parsers.context import is_table_title
from ..parsers.models import ParsedPdfItem
from .text import CHARS_PER_TOKEN_GUARD, _token_count, _too_large, split_text


@dataclass(frozen=True)
class TableRow:
    text: str
    chunk_type: str
    page_start: int | None
    page_end: int | None
    section_title: str | None
    section_path: list[str]
    parent_section_id: str | None
    parser: str
    quality_flags: list[str]
    table_json: dict[str, object] | None
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


def table_chunks(
    item: ParsedPdfItem,
    target_tokens: int,
    *,
    table_title_hint: str = "",
    include_row_chunks: bool = True,
) -> list[TableRow]:
    full_table_chunks = _full_table_chunks(item, target_tokens, table_title_hint=table_title_hint)
    if not include_row_chunks:
        return full_table_chunks
    return [*full_table_chunks, *_table_row_chunks(item, target_tokens, table_title_hint=table_title_hint)]


def form_like_record_chunks(items: list[ParsedPdfItem], target_tokens: int) -> list[TableRow]:
    fields = _form_like_fields(items)
    if not fields:
        return []
    return _bounded_form_like_record_chunks(items, fields, target_tokens=target_tokens)


def _full_table_chunks(item: ParsedPdfItem, target_tokens: int, *, table_title_hint: str) -> list[TableRow]:
    max_chars = target_tokens * CHARS_PER_TOKEN_GUARD
    if not _too_large(item.text, target_tokens, max_chars):
        return [_table_row(item.text, item, chunk_type="table", table_title_hint=table_title_hint)]
    lines = [line for line in item.text.splitlines() if line.strip()]
    header = _header_lines(lines)
    body = lines[len(header) :]
    chunks: list[TableRow] = []
    current: list[str] = []
    header_text = "\n".join(header)
    for row in body:
        candidate = "\n".join([*header, *current, row])
        if current and _too_large(candidate, target_tokens, max_chars):
            chunks.extend(_bounded_rows("\n".join([*header, *current]), item, target_tokens, table_title_hint=table_title_hint))
            current = []
        if not current and _too_large("\n".join([header_text, row]), target_tokens, max_chars):
            chunks.extend(_oversized_row_chunks(header_text, row, item, target_tokens, table_title_hint=table_title_hint))
            continue
        current.append(row)
    if current or not chunks:
        chunks.extend(_bounded_rows("\n".join([*header, *current]), item, target_tokens, table_title_hint=table_title_hint))
    return chunks


def _header_lines(lines: list[str]) -> list[str]:
    if len(lines) > 2 and set(lines[1].replace("|", "").strip()) <= {"-", ":"}:
        return lines[:2]
    return lines[:1]


def _oversized_row_chunks(header_text: str, row: str, item: ParsedPdfItem, target_tokens: int, *, table_title_hint: str) -> list[TableRow]:
    header_tokens = _token_count(header_text)
    budget = max(1, target_tokens - header_tokens)
    max_chars = target_tokens * CHARS_PER_TOKEN_GUARD
    piece_max_chars = max(1, max_chars - len(header_text) - 1)
    if len(header_text) >= max_chars:
        return _bounded_rows("\n".join([header_text, row]), item, target_tokens, table_title_hint=table_title_hint)
    rows: list[TableRow] = []
    for piece in _row_pieces(row, target_tokens=budget, max_chars=piece_max_chars):
        rows.extend(_bounded_rows("\n".join([header_text, piece]), item, target_tokens, table_title_hint=table_title_hint))
    return rows


def _row_pieces(row: str, target_tokens: int, max_chars: int) -> list[str]:
    pieces: list[str] = []
    for piece in split_text(row, target_tokens=target_tokens, overlap_tokens=0):
        pieces.extend(piece[start : start + max_chars] for start in range(0, len(piece), max_chars))
    return [piece for piece in pieces if piece]


def _bounded_rows(text: str, item: ParsedPdfItem, target_tokens: int, *, table_title_hint: str) -> list[TableRow]:
    max_chars = target_tokens * CHARS_PER_TOKEN_GUARD
    if not _too_large(text, target_tokens, max_chars):
        return [_table_row(text, item, chunk_type="table", table_title_hint=table_title_hint)]
    return [
        _table_row(piece, item, chunk_type="table", table_title_hint=table_title_hint)
        for piece in split_text(text, target_tokens=target_tokens, overlap_tokens=0)
    ]


def _table_row_chunks(item: ParsedPdfItem, target_tokens: int, *, table_title_hint: str) -> list[TableRow]:
    headers, body = _structured_table_rows(item)
    if not headers or not body:
        return []
    table_title = _table_title(item, table_title_hint=table_title_hint)
    table_caption = _table_caption(item)
    section = _section_label(item)
    chunks: list[TableRow] = []
    for row_index, row in enumerate(body):
        label, values = _row_label_and_values(row)
        if not label:
            continue
        structured_fields = _structured_fields_for_row(headers, row)
        text = _table_row_text(
            table_title=table_title,
            section=section,
            headers=headers,
            label=label,
            values=values,
        )
        chunks.extend(
            _bounded_table_row_chunks(
                text,
                item,
                target_tokens,
                table_title=table_title,
                table_caption=table_caption,
                row_label=label,
                headers=headers,
                row_index=row_index,
                structured_fields=structured_fields,
            )
        )
    return chunks


def _structured_table_rows(item: ParsedPdfItem) -> tuple[list[str], list[list[str]]]:
    rows = _table_json_rows(item.table_json)
    if not rows:
        rows = _markdown_rows(item.text)
    if len(rows) < 2:
        return [], []
    headers = [_clean_cell(cell) for cell in rows[0]]
    body = [[_clean_cell(cell) for cell in row] for row in rows[1:] if not _is_separator_row(row)]
    return headers, [row for row in body if any(row)]


def _table_json_rows(table_json: dict[str, object] | None) -> list[list[str]]:
    if not isinstance(table_json, dict):
        return []
    rows = table_json.get("rows")
    if not isinstance(rows, list):
        return []
    normalized: list[list[str]] = []
    for row in rows:
        if isinstance(row, list):
            normalized.append([_clean_cell(cell) for cell in row])
    return normalized


def _markdown_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [_clean_cell(cell) for cell in stripped.strip("|").split("|")]
        if cells and not _is_separator_row(cells):
            rows.append(cells)
    return rows


def _is_separator_row(row: list[str]) -> bool:
    cells = [_clean_cell(cell) for cell in row]
    return bool(cells) and all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _row_label_and_values(row: list[str]) -> tuple[str, list[str]]:
    for index, cell in enumerate(row):
        if cell:
            values = [_clean_cell(value) for value in [*row[:index], *row[index + 1 :]] if _clean_cell(value)]
            return cell, values
    return "", []


def _structured_fields_for_row(headers: list[str], row: list[str]) -> list[dict[str, str]]:
    header_fields = _header_mapped_fields(headers, row)
    alternating_fields = _alternating_row_fields(row)
    if _field_score(alternating_fields, penalize_generic=False) > _field_score(header_fields, penalize_generic=True):
        return alternating_fields
    return header_fields


def _header_mapped_fields(headers: list[str], row: list[str]) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for header, value in zip(headers, row, strict=False):
        label = _clean_cell(header)
        normalized_value = _clean_cell(value)
        if not label or not normalized_value:
            continue
        fields.append({"label": label, "value": normalized_value})
    return fields


def _alternating_row_fields(row: list[str]) -> list[dict[str, str]]:
    cells = [_clean_cell(cell) for cell in row if _clean_cell(cell)]
    if len(cells) < 2:
        return []
    if len(cells) % 2 != 0:
        return []
    fields: list[dict[str, str]] = []
    for index in range(0, len(cells), 2):
        label = cells[index]
        value = cells[index + 1]
        if not _looks_like_field_label(label) or not value:
            return []
        fields.append({"label": label.rstrip(":"), "value": value})
    return fields


def _field_score(fields: list[dict[str, str]], *, penalize_generic: bool) -> int:
    score = 0
    for structured_field in fields:
        label = collapse_whitespace(structured_field.get("label"))
        value = collapse_whitespace(structured_field.get("value"))
        if not label or not value:
            continue
        score += 1
        if _looks_like_field_label(label):
            score += 2
        if penalize_generic and _is_uninformative_header(label):
            score -= 2
    return score


def _looks_like_field_label(label: str) -> bool:
    normalized = collapse_whitespace(label).strip(":")
    if not normalized:
        return False
    tokens = normalized.split()
    if len(tokens) > 8:
        return False
    alpha_count = sum(1 for char in normalized if char.isalpha())
    digit_count = sum(1 for char in normalized if char.isdigit())
    return alpha_count >= max(1, digit_count)


def _is_uninformative_header(label: str) -> bool:
    normalized = collapse_whitespace(label).strip(":").lower()
    if not normalized:
        return True
    if normalized.isdecimal():
        return True
    return normalized in {"col", "column", "field", "label", "value", "name", "description"}


def _table_row_text(*, table_title: str, section: str, headers: list[str], label: str, values: list[str]) -> str:
    lines: list[str] = []
    if table_title:
        lines.append(f"[Table: {table_title}]")
    if section:
        lines.append(f"[Section: {section}]")
    if headers:
        lines.append(f"[Columns: {' | '.join(headers)}]")
    lines.append(f"Row: {label}")
    if values:
        lines.append(f"Value: {' | '.join(values)}")
    return "\n".join(lines)


def _bounded_table_row_chunks(
    text: str,
    item: ParsedPdfItem,
    target_tokens: int,
    *,
    table_title: str,
    table_caption: str,
    row_label: str,
    headers: list[str],
    row_index: int,
    structured_fields: list[dict[str, str]],
) -> list[TableRow]:
    max_chars = target_tokens * CHARS_PER_TOKEN_GUARD
    structured_kind = "table_row" if structured_fields else ""
    if not _too_large(text, target_tokens, max_chars):
        return [
            _row(
                text,
                item,
                chunk_type="table_row",
                table_title=table_title,
                table_caption=table_caption,
                table_row_label=row_label,
                table_column_headers=headers,
                table_row_index=row_index,
                structured_kind=structured_kind,
                structured_fields=structured_fields,
            )
        ]
    return [
        _row(
            piece,
            item,
            chunk_type="table_row",
            table_title=table_title,
            table_caption=table_caption,
            table_row_label=row_label,
            table_column_headers=headers,
            table_row_index=row_index,
            structured_kind=structured_kind,
            structured_fields=structured_fields,
        )
        for piece in split_text(text, target_tokens=target_tokens, overlap_tokens=0)
    ]


def _table_title(item: ParsedPdfItem, *, table_title_hint: str = "") -> str:
    return _table_caption(item) or _text_table_title(item.text) or table_title_hint or item.section_title or (item.section_path[-1] if item.section_path else "")


def _table_caption(item: ParsedPdfItem) -> str:
    table_json = item.table_json
    if isinstance(table_json, dict):
        caption = table_json.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption.strip()
    return ""


def _table_column_headers(item: ParsedPdfItem) -> list[str]:
    headers, _ = _structured_table_rows(item)
    return headers


def _section_label(item: ParsedPdfItem) -> str:
    if item.section_path:
        return " / ".join(part for part in item.section_path if part)
    return item.section_title or ""


def _clean_cell(value: object) -> str:
    return " ".join(str(value or "").replace("\\|", "|").split())


def _text_table_title(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip()
        if is_table_title(candidate):
            return candidate
    return ""


def _table_row(text: str, item: ParsedPdfItem, *, chunk_type: str, table_title_hint: str) -> TableRow:
    return _row(
        text,
        item,
        chunk_type=chunk_type,
        table_title=_table_title(item, table_title_hint=table_title_hint),
        table_caption=_table_caption(item),
        table_column_headers=_table_column_headers(item),
    )


def _row(
    text: str,
    item: ParsedPdfItem,
    *,
    chunk_type: str,
    table_title: str = "",
    table_caption: str = "",
    table_row_label: str = "",
    table_column_headers: list[str] | None = None,
    table_row_index: int | None = None,
    structured_kind: str = "",
    structured_fields: list[dict[str, str]] | None = None,
) -> TableRow:
    normalized_structured_fields = _normalized_structured_fields(structured_fields or [])
    return TableRow(
        text=text,
        chunk_type=chunk_type,
        page_start=item.page_start,
        page_end=item.page_end,
        section_title=item.section_title,
        section_path=item.section_path,
        parent_section_id=item.parent_section_id,
        parser=item.parser,
        quality_flags=item.quality_flags,
        table_json=item.table_json,
        table_title=table_title,
        table_caption=table_caption,
        table_row_label=table_row_label,
        table_column_headers=table_column_headers or [],
        table_row_index=table_row_index,
        structured_kind=structured_kind,
        structured_fields=normalized_structured_fields,
        structured_field_names=normalized_field_names(normalized_structured_fields),
        structured_field_values=normalized_field_values(normalized_structured_fields),
        structured_search_text=canonical_structured_search_text(normalized_structured_fields),
        source_regions=_source_regions(item, text=text, chunk_type=chunk_type),
    )


def _normalized_structured_fields(fields: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for structured_field in fields:
        label = collapse_whitespace(structured_field.get("label"))
        value = collapse_whitespace(structured_field.get("value"))
        if not label or not value:
            continue
        normalized.append({"label": label.rstrip(":"), "value": value})
    return normalized


def _bounded_form_like_record_chunks(
    items: list[ParsedPdfItem],
    fields: list[dict[str, str]],
    *,
    target_tokens: int,
) -> list[TableRow]:
    section = _section_label(items[0]) if items else ""
    grouped_fields: list[list[dict[str, str]]] = []
    current_fields: list[dict[str, str]] = []
    for structured_field in fields:
        candidate_fields = [*current_fields, structured_field]
        candidate_text = _structured_record_text(section=section, fields=candidate_fields)
        if current_fields and _too_large(candidate_text, target_tokens, target_tokens * CHARS_PER_TOKEN_GUARD):
            grouped_fields.append(current_fields)
            current_fields = [structured_field]
            continue
        current_fields = candidate_fields
    if current_fields:
        grouped_fields.append(current_fields)
    chunks: list[TableRow] = []
    for chunk_fields in grouped_fields:
        text = _structured_record_text(section=section, fields=chunk_fields)
        if _too_large(text, target_tokens, target_tokens * CHARS_PER_TOKEN_GUARD):
            for piece in split_text(text, target_tokens=target_tokens, overlap_tokens=0):
                chunks.append(
                    _record_row(
                        piece,
                        items,
                        chunk_type="text",
                        section=section,
                        structured_fields=chunk_fields,
                    )
                )
            continue
        chunks.append(
            _record_row(
                text,
                items,
                chunk_type="text",
                section=section,
                structured_fields=chunk_fields,
            )
        )
    return chunks


def _structured_record_text(*, section: str, fields: list[dict[str, str]]) -> str:
    lines: list[str] = []
    if section:
        lines.append(f"[Section: {section}]")
    lines.extend(f"{field['label']}: {field['value']}" for field in fields)
    return "\n".join(lines)


def _record_row(
    text: str,
    items: list[ParsedPdfItem],
    *,
    chunk_type: str,
    section: str,
    structured_fields: list[dict[str, str]],
) -> TableRow:
    source_item = items[0]
    normalized_fields = _normalized_structured_fields(structured_fields)
    return TableRow(
        text=text,
        chunk_type=chunk_type,
        page_start=source_item.page_start,
        page_end=items[-1].page_end or items[-1].page_start,
        section_title=source_item.section_title,
        section_path=source_item.section_path,
        parent_section_id=source_item.parent_section_id,
        parser=source_item.parser,
        quality_flags=sorted({flag for item in items for flag in item.quality_flags}),
        table_json=None,
        structured_kind="kv_record",
        structured_fields=normalized_fields,
        structured_field_names=normalized_field_names(normalized_fields),
        structured_field_values=normalized_field_values(normalized_fields),
        structured_search_text=canonical_structured_search_text(normalized_fields),
        source_regions=_source_regions_for_items(items, chunk_type="kv_record"),
    )


def _form_like_fields(items: list[ParsedPdfItem]) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for item in items:
        fields.extend(_extract_inline_key_value_fields(item.text))
    return _normalized_structured_fields(fields)


def _extract_inline_key_value_fields(text: str) -> list[dict[str, str]]:
    line_fields = _line_delimited_fields(text)
    if line_fields:
        return line_fields
    normalized = collapse_whitespace(text)
    if not normalized:
        return []
    fields = _colon_delimited_fields(normalized)
    if fields:
        return fields
    return _alternating_row_fields(normalized.split("|"))


def _line_delimited_fields(text: str) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = collapse_whitespace(raw_line)
        if not line or ":" not in line:
            continue
        label, value = line.split(":", 1)
        label = collapse_whitespace(label).rstrip(":")
        value = collapse_whitespace(value.strip(" |,;"))
        if _looks_like_field_label(label) and value:
            fields.append({"label": label, "value": value})
    return fields


def _colon_delimited_fields(text: str) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    matches = list(re.finditer(r"(?P<label>[A-Za-z][A-Za-z0-9./&()\- ]{0,60}?)\s*:\s*", text))
    if not matches:
        return []
    for index, match in enumerate(matches):
        value_start = match.end()
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = collapse_whitespace(match.group("label")).rstrip(":")
        value = collapse_whitespace(text[value_start:value_end].strip(" |,;"))
        if label and value:
            fields.append({"label": label, "value": value})
    return fields


def _source_regions_for_items(items: list[ParsedPdfItem], *, chunk_type: str) -> list[dict[str, object]]:
    regions: list[dict[str, object]] = []
    for item in items:
        if item.bbox is None or item.page_start is None:
            continue
        regions.append(
            {
                "page": item.page_start,
                "bbox": [float(value) for value in item.bbox],
                "text": item.text,
                "region_type": chunk_type,
                "confidence": item.confidence,
            }
        )
    return regions


def _source_regions(item: ParsedPdfItem, *, text: str, chunk_type: str) -> list[dict[str, object]]:
    if item.bbox is None or item.page_start is None:
        return []
    return [
        {
            "page": item.page_start,
            "bbox": [float(value) for value in item.bbox],
            "text": text,
            "region_type": chunk_type,
            "confidence": item.confidence,
        }
    ]
