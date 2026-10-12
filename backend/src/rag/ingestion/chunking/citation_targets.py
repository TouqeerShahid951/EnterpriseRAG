"""Build deterministic viewer targets from parsed document items."""

from __future__ import annotations

from ..parsers.models import ParsedPdfItem


def citation_targets(
    items: list[ParsedPdfItem], *, table_row_index: int | None = None
) -> list[dict[str, object]]:
    targets: list[dict[str, object]] = []
    for index, item in enumerate(items):
        if item.source_spans:
            for span in item.source_spans:
                if item.quote_texts is not None and not any(
                    span["exact_text"].strip()
                    and f" {' '.join(span['exact_text'].split())} " in f" {' '.join(text.split())} "
                    for text in item.quote_texts
                ):
                    continue
                target = {**(_citation_target(item, table_row_index=table_row_index, prefix="", suffix="") or {}),
                          "page": span["page"], "bbox": span["bbox"], "exact_text": span["exact_text"],
                          "provenance_kind": "ocr" if item.quote_texts is not None else _provenance(item)}
                if target not in targets:
                    targets.append(target)
            if item.quote_texts is None:
                continue
        target = _citation_target(
            item,
            table_row_index=table_row_index,
            # Appended image descriptions are not adjacent text in the Word file.
            prefix=items[index - 1].text[-80:]
            if index and "source:docx_structured" in items[index - 1].quality_flags
            else "",
            suffix=items[index + 1].text[:80]
            if index + 1 < len(items)
            and "source:docx_structured" in items[index + 1].quality_flags
            else "",
        )
        if target is not None:
            target["provenance_kind"] = _provenance(item)
        if target is not None and target not in targets:
            targets.append(target)
        if target is not None and item.quote_texts is not None:
            for text in item.quote_texts:
                if text and text in item.text:
                    targets.append({**target, "exact_text": text, "provenance_kind": "ocr"})
    return targets


def _citation_target(
    item: ParsedPdfItem,
    *,
    table_row_index: int | None,
    prefix: str,
    suffix: str,
) -> dict[str, object] | None:
    spreadsheet = _spreadsheet_metadata(item)
    if spreadsheet:
        return _spreadsheet_target(item, spreadsheet, table_row_index)
    json_pointer = _json_pointer(item, table_row_index)
    if json_pointer is not None:
        return {"kind": "json", "pointer": json_pointer, "exact_text": item.text}
    flags = set(item.quality_flags)
    if "source:docx_structured" in flags and item.text.strip():
        return {
            "kind": "text",
            "exact_text": _docx_exact_text(item),
            "prefix": prefix.strip(),
            "suffix": suffix.strip(),
        }
    if item.image_source_kind == "docx_media" and item.image_asset_id:
        return {
            "kind": "image",
            "bbox": (
                [float(value) for value in item.bbox] if item.bbox is not None else None
            ),
            "exact_text": item.text,
            "confidence": item.confidence,
            "image_asset_id": item.image_asset_id,
            "image_source_kind": item.image_source_kind,
            "extraction_method": item.extraction_method,
        }
    if item.page_start is not None and item.bbox is not None:
        kind = (
            "slide"
            if any(flag.startswith("source:pptx_") for flag in flags)
            else "image"
            if flags.intersection({"source:image_file", "source:docx_media"})
            else "page"
        )
        target: dict[str, object] = {
            "kind": kind,
            "bbox": [float(value) for value in item.bbox],
            "exact_text": item.text,
            "confidence": item.confidence,
            "image_asset_id": item.image_asset_id,
            "image_source_kind": item.image_source_kind,
            "extraction_method": item.extraction_method,
        }
        if kind != "image":
            target["page"] = item.page_start
            target["region_type"] = item.item_type
        return target
    if item.text.strip():
        return {"kind": "text", "exact_text": item.text.strip()}
    return None


def _docx_exact_text(item: ParsedPdfItem) -> str:
    rows = item.table_json.get("rows") if isinstance(item.table_json, dict) else None
    if not isinstance(rows, list):
        return item.text.strip()
    cells = [
        " ".join(cell.replace("<!-- image -->", "").split())
        for row in rows
        if isinstance(row, list)
        for cell in row
        if isinstance(cell, str)
    ]
    return " ".join(filter(None, cells)) or item.text.strip()


def _spreadsheet_metadata(item: ParsedPdfItem) -> dict[str, object]:
    table = item.table_json
    metadata = table.get("spreadsheet") if isinstance(table, dict) else None
    return dict(metadata) if isinstance(metadata, dict) else {}


def _spreadsheet_target(
    item: ParsedPdfItem,
    metadata: dict[str, object],
    table_row_index: int | None,
) -> dict[str, object]:
    raw_rows = metadata.get("data_row_numbers")
    data_rows = (
        [value for value in raw_rows if isinstance(value, int)]
        if isinstance(raw_rows, list)
        else []
    )
    header_rows = [
        value for value in metadata.get("header_rows", []) if isinstance(value, int)
    ]
    column_count = max(1, int(metadata.get("column_count") or 1))
    if table_row_index is not None and table_row_index < len(data_rows):
        start_row = data_rows[table_row_index] - 1
        end_row = start_row + 1
    elif "spreadsheet_schema" in item.quality_flags and header_rows:
        start_row = min(header_rows) - 1
        end_row = max(header_rows)
    elif data_rows:
        start_row = min(data_rows) - 1
        end_row = max(data_rows)
    else:
        start_row = 0
        end_row = 1
    return {
        "kind": "spreadsheet",
        "sheet_name": str(metadata.get("source_name") or item.section_title or "Sheet"),
        "start_row": start_row,
        "end_row": end_row,
        "start_column": 0,
        "end_column": column_count,
        "exact_text": item.text,
    }


def _json_pointer(item: ParsedPdfItem, table_row_index: int | None) -> str | None:
    if not any(flag.startswith("source:json") for flag in item.quality_flags):
        return None
    table = item.table_json or {}
    row_pointers = table.get("row_pointers")
    if (
        table_row_index is not None
        and isinstance(row_pointers, list)
        and table_row_index < len(row_pointers)
    ):
        pointer = row_pointers[table_row_index]
        if isinstance(pointer, str):
            return pointer
    pointer = table.get("json_pointer")
    return pointer if isinstance(pointer, str) else ""


def _provenance(item: ParsedPdfItem) -> str:
    flags = set(item.quality_flags)
    if item.extraction_method == "vision_ocr_description" or "full_slide_visual" in flags:
        return "generated"
    if any("ocr" in flag.lower() for flag in flags):
        return "ocr"
    if any(flag.startswith(("source:json", "source:xlsx", "source:csv", "source:spreadsheet")) for flag in flags):
        return "structured"
    if flags.intersection({"source:docx_structured", "source:pymupdf_native", "source:pptx_structured", "source:pptx_chart", "source:docling", "source:docling_layout"}):
        return "native"
    return "unknown"
