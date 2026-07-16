"""Deterministic JSON parser for ingestion."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from rag.ingestion.errors import UnsupportedDocumentError, WorkerStepError
from rag.ingestion.parsers.models import DocumentParseResult, ParsedPdfItem
from rag.ingestion.parsers.provenance import base_report

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_TABLE_HEADERS = 80
_MAX_RECORD_FIELDS = 80
_MAX_ARRAY_VALUES = 200


def parse_json_document(file_bytes: bytes) -> DocumentParseResult:
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkerStepError("json_parse_failed", "JSON must be valid UTF-8.") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkerStepError("json_parse_failed", "JSON could not be parsed.") from exc

    items: list[ParsedPdfItem] = []
    _walk_json(value, (), items)
    if not items:
        raise UnsupportedDocumentError()

    return DocumentParseResult(
        items=_renumber_items(items),
        provenance=base_report(
            document_kind="json",
            page_count=None,
            primary_parser="json",
            secondary_parser=None,
            routing_mode="json_structure",
            config={"path_style": "dot_bracket"},
            items=items,
        ),
    )


def _walk_json(value: Any, path: tuple[object, ...], items: list[ParsedPdfItem]) -> None:
    explicit_table = _explicit_table_rows(value)
    if explicit_table is not None:
        headers, rows = explicit_table
        _append_table_item(
            items,
            path,
            headers=headers,
            rows=rows,
            quality_flags=["source:json", "json_table"],
            row_paths=[_format_path((*path, "rows", index)) for index in range(len(rows))],
        )
        return

    if isinstance(value, dict):
        if not value:
            _append_leaf_item(items, path, "empty object")
            return
        primitive_fields = [
            (str(key), child)
            for key, child in value.items()
            if _is_scalar(child)
        ]
        if primitive_fields:
            _append_record_item(items, path, primitive_fields)
        for key, child in value.items():
            if not _is_scalar(child):
                _walk_json(child, (*path, str(key)), items)
        return

    if isinstance(value, list):
        if not value:
            _append_leaf_item(items, path, "empty array")
            return
        object_table = _array_object_table_rows(value)
        if object_table is not None:
            headers, rows = object_table
            _append_table_item(
                items,
                path,
                headers=headers,
                rows=rows,
                quality_flags=["source:json", "json_array_table"],
                row_paths=[_format_path((*path, index)) for index in range(len(rows))],
            )
        if value and all(_is_scalar(item) for item in value):
            _append_array_item(items, path, value)
            return
        for index, child in enumerate(value):
            if not _is_scalar(child):
                _walk_json(child, (*path, index), items)
        return

    _append_leaf_item(items, path, value)


def _append_record_item(items: list[ParsedPdfItem], path: tuple[object, ...], fields: list[tuple[str, Any]]) -> None:
    scoped = fields[:_MAX_RECORD_FIELDS]
    lines = [f"JSON path: {_format_path(path)}"]
    for key, value in scoped:
        display_key = _display_key(key)
        lines.append(f"{display_key}: {_format_scalar(value)}")
        if display_key != key:
            lines.append(f"JSON key for {display_key}: {key}")
        lines.append(f"JSON path for {display_key}: {_format_path((*path, key))}")
    if len(fields) > len(scoped):
        lines.append(f"Additional fields omitted: {len(fields) - len(scoped)}")
    items.append(
        _item(
            text="\n".join(lines),
            item_type="text",
            path=path,
            quality_flags=["source:json", "form_like_layout", "json_object"],
        )
    )


def _append_array_item(items: list[ParsedPdfItem], path: tuple[object, ...], values: list[Any]) -> None:
    scoped = values[:_MAX_ARRAY_VALUES]
    lines = [
        f"JSON path: {_format_path(path)}",
        "Values: " + " | ".join(_format_scalar(value) for value in scoped),
    ]
    lines.extend(
        f"JSON path for value {index}: {_format_path((*path, index))}"
        for index, _ in enumerate(scoped)
    )
    if len(values) > len(scoped):
        lines.append(f"Additional values omitted: {len(values) - len(scoped)}")
    items.append(
        _item(
            text="\n".join(lines),
            item_type="text",
            path=path,
            quality_flags=["source:json", "form_like_layout", "json_array"],
        )
    )


def _append_leaf_item(items: list[ParsedPdfItem], path: tuple[object, ...], value: Any) -> None:
    items.append(
        _item(
            text=f"JSON path: {_format_path(path)}\nValue: {_format_scalar(value)}",
            item_type="text",
            path=path,
            quality_flags=["source:json", "form_like_layout", "json_value"],
        )
    )


def _append_table_item(
    items: list[ParsedPdfItem],
    path: tuple[object, ...],
    *,
    headers: list[str],
    rows: list[list[Any]],
    quality_flags: list[str],
    row_paths: list[str] | None = None,
) -> None:
    if not headers or not rows:
        return
    normalized_headers = [_clean_cell(header) for header in headers[:_MAX_TABLE_HEADERS]]
    normalized_rows_with_paths = [
        (index, [_clean_cell(value) for value in row[: len(normalized_headers)]])
        for index, row in enumerate(rows)
        if any(_clean_cell(value) for value in row)
    ]
    if not normalized_rows_with_paths:
        return
    if row_paths:
        normalized_headers = [*normalized_headers, "JSON path"]
        normalized_rows = [
            [*row, _clean_cell(row_paths[index]) if index < len(row_paths) else ""]
            for index, row in normalized_rows_with_paths
        ]
    else:
        normalized_rows = [row for _, row in normalized_rows_with_paths]
    markdown_rows = [
        "| " + " | ".join(normalized_headers) + " |",
        "| " + " | ".join("---" for _ in normalized_headers) + " |",
        *["| " + " | ".join(row) + " |" for row in normalized_rows[:200]],
    ]
    items.append(
        _item(
            text=f"JSON table: {_format_path(path)}\n" + "\n".join(markdown_rows),
            item_type="table",
            path=path,
            quality_flags=quality_flags,
            table_json={"caption": _format_path(path), "rows": [normalized_headers, *normalized_rows]},
        )
    )


def _explicit_table_rows(value: Any) -> tuple[list[str], list[list[Any]]] | None:
    if not isinstance(value, dict):
        return None
    headers = value.get("headers")
    rows = value.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list):
        return None
    normalized_headers = [_clean_cell(header) for header in headers if _clean_cell(header)]
    if not normalized_headers:
        return None
    normalized_rows: list[list[Any]] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("values"), list):
            normalized_rows.append(list(row["values"]))
        elif isinstance(row, dict):
            normalized_rows.append([row.get(header, "") for header in normalized_headers])
        elif isinstance(row, list):
            normalized_rows.append(list(row))
    normalized_rows = [_pad_row(row, len(normalized_headers)) for row in normalized_rows]
    return (normalized_headers, normalized_rows) if normalized_rows else None


def _array_object_table_rows(value: list[Any]) -> tuple[list[str], list[list[Any]]] | None:
    if len(value) < 2 or not all(isinstance(item, dict) for item in value):
        return None
    headers: list[str] = []
    for item in value:
        assert isinstance(item, dict)
        for key, child in item.items():
            if not _is_scalar(child):
                continue
            label = str(key)
            if label not in headers:
                headers.append(label)
            if len(headers) > _MAX_TABLE_HEADERS:
                return None
    if not headers:
        return None
    rows = [
        [item.get(header, "") if isinstance(item, dict) else "" for header in headers]
        for item in value
    ]
    return headers, rows


def _item(
    *,
    text: str,
    item_type: str,
    path: tuple[object, ...],
    quality_flags: list[str],
    table_json: dict[str, Any] | None = None,
) -> ParsedPdfItem:
    path_text = _format_path(path)
    return ParsedPdfItem(
        index=0,
        text=text,
        item_type=item_type,
        page_start=None,
        page_end=None,
        section_title=path_text,
        section_path=[path_text] if path_text else [],
        parent_section_id=path_text,
        parser="json",
        quality_flags=quality_flags,
        table_json=table_json,
        extraction_method="json_path",
    )


def _format_path(path: tuple[object, ...]) -> str:
    if not path:
        return "$"
    result = ""
    for part in path:
        if isinstance(part, int):
            result += f"[{part}]"
            continue
        key = str(part)
        if not result and _IDENTIFIER_RE.match(key):
            result = key
        elif _IDENTIFIER_RE.match(key):
            result += f".{key}"
        else:
            result += "[" + json.dumps(key, ensure_ascii=False) + "]"
    return result or "$"


def _format_scalar(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _display_key(key: str) -> str:
    return " ".join(key.replace("_", " ").replace("-", " ").split()) or key


def _clean_cell(value: Any) -> str:
    return " ".join(str(value if value is not None else "").replace("|", "\\|").split())


def _pad_row(row: list[Any], width: int) -> list[Any]:
    if len(row) >= width:
        return row[:width]
    return [*row, *([""] * (width - len(row)))]


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _renumber_items(items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    return [replace(item, index=index) for index, item in enumerate(items)]
