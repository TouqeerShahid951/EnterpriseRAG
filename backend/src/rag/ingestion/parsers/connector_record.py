"""Parser for connector records in direct chunk mode."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from ..errors import UnsupportedDocumentError, WorkerStepError
from .models import DocumentParseResult, ParsedPdfItem
from .provenance import base_report


def parse_connector_record_document(file_bytes: bytes) -> DocumentParseResult:
    try:
        payload = json.loads(file_bytes.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise WorkerStepError("connector_record_parse_failed", "Connector record must be valid UTF-8.") from exc
    except json.JSONDecodeError as exc:
        raise WorkerStepError("connector_record_parse_failed", "Connector record could not be parsed.") from exc
    if not isinstance(payload, dict):
        raise UnsupportedDocumentError()
    records = payload.get("records")
    if isinstance(records, list):
        items = [_record_item(record, index) for index, record in enumerate(records) if isinstance(record, dict)]
    else:
        items = [_record_item(payload, 0)]
    items = [item for item in items if item.text.strip()]
    if not items:
        raise UnsupportedDocumentError()
    items = [replace(item, index=index) for index, item in enumerate(items)]
    return DocumentParseResult(
        items=items,
        provenance=base_report(
            document_kind="connector_record",
            page_count=None,
            primary_parser="connector_record",
            secondary_parser=None,
            routing_mode="direct_chunks",
            config={"mode": "direct_chunks"},
            items=items,
        ),
    )


def _record_item(record: dict[str, Any], index: int) -> ParsedPdfItem:
    data = record.get("data") if isinstance(record.get("data"), dict) else record
    identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    title = str(record.get("title") or record.get("source_path") or "Connector record")
    lines = [f"Connector record: {title}"]
    if identity:
        lines.append("Identity: " + ", ".join(f"{key}={_scalar(value)}" for key, value in identity.items()))
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            lines.append(f"{_label(key)}: {json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)}")
        else:
            lines.append(f"{_label(key)}: {_scalar(value)}")
    return ParsedPdfItem(
        index=index,
        text="\n".join(lines),
        item_type="text",
        page_start=None,
        page_end=None,
        section_title=title,
        section_path=[title],
        parent_section_id=title,
        parser="connector_record",
        quality_flags=["source:connector", "connector_record", "direct_chunks"],
        extraction_method="connector_record",
    )


def _label(value: object) -> str:
    return " ".join(str(value).replace("_", " ").replace("-", " ").split())


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return " ".join(str(value).split())
