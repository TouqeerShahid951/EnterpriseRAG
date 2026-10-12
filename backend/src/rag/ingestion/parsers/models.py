"""Shared PDF parsing dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator
import math

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class ParsedPdfItem:
    index: int
    text: str
    item_type: str
    page_start: int | None
    page_end: int | None
    section_title: str | None = None
    section_path: list[str] = field(default_factory=list)
    section_level: int | None = None
    parent_section_id: str | None = None
    bbox: BBox | None = None
    parser: str = "pymupdf"
    quality_flags: list[str] = field(default_factory=list)
    table_json: dict[str, Any] | None = None
    confidence: float | None = None
    image_asset_id: str | None = None
    image_source_kind: str | None = None
    image_content_type: str | None = None
    extraction_method: str | None = None
    source_spans: list[dict[str, Any]] = field(default_factory=list)
    quote_texts: list[str] | None = None


@dataclass(frozen=True)
class ParsedImageAsset:
    id: str
    source_kind: str
    object_path: str
    content_type: str
    content_hash: str
    page: int | None = None
    bbox: BBox | None = None
    width: int | None = None
    height: int | None = None
    extracted_text: str | None = None
    caption: str | None = None
    confidence: float | None = None
    quality_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentParseResult:
    items: list[ParsedPdfItem]
    provenance: dict[str, Any]
    assets: list[ParsedImageAsset] = field(default_factory=list)

    def __iter__(self) -> Iterator[ParsedPdfItem]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> ParsedPdfItem:
        return self.items[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return self.items == other
        if isinstance(other, DocumentParseResult):
            return self.items == other.items and self.provenance == other.provenance and self.assets == other.assets
        return False


def parsed_item_to_dict(item: ParsedPdfItem) -> dict[str, Any]:
    return {
        "index": item.index,
        "text": item.text,
        "item_type": item.item_type,
        "page_start": item.page_start,
        "page_end": item.page_end,
        "section_title": item.section_title,
        "section_path": list(item.section_path),
        "section_level": item.section_level,
        "parent_section_id": item.parent_section_id,
        "bbox": list(item.bbox) if item.bbox is not None else None,
        "parser": item.parser,
        "quality_flags": list(item.quality_flags),
        "table_json": item.table_json,
        "confidence": item.confidence,
        "image_asset_id": item.image_asset_id,
        "image_source_kind": item.image_source_kind,
        "image_content_type": item.image_content_type,
        "extraction_method": item.extraction_method,
        "source_spans": item.source_spans,
        "quote_texts": item.quote_texts,
    }


def parsed_item_from_dict(payload: dict[str, Any]) -> ParsedPdfItem:
    raw_quotes = payload.get("quote_texts")
    if raw_quotes is not None and (not isinstance(raw_quotes, list) or any(not isinstance(text, str) for text in raw_quotes)):
        raise ValueError("quote_texts must contain original text strings")
    raw_bbox = payload.get("bbox")
    bbox: BBox | None = None
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        bbox = (float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3]))
    raw_path = payload.get("section_path")
    raw_flags = payload.get("quality_flags")
    raw_table = payload.get("table_json")
    confidence = payload.get("confidence")
    return ParsedPdfItem(
        index=int(payload.get("index", 0)),
        text=str(payload.get("text") or ""),
        item_type=str(payload.get("item_type") or "text"),
        page_start=_int_or_none(payload.get("page_start")),
        page_end=_int_or_none(payload.get("page_end")),
        section_title=str(payload["section_title"]) if payload.get("section_title") is not None else None,
        section_path=[str(item) for item in raw_path] if isinstance(raw_path, list) else [],
        section_level=_int_or_none(payload.get("section_level")),
        parent_section_id=str(payload["parent_section_id"]) if payload.get("parent_section_id") is not None else None,
        bbox=bbox,
        parser=str(payload.get("parser") or "pymupdf"),
        quality_flags=[str(item) for item in raw_flags] if isinstance(raw_flags, list) else [],
        table_json=raw_table if isinstance(raw_table, dict) else None,
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        image_asset_id=str(payload["image_asset_id"]) if payload.get("image_asset_id") is not None else None,
        image_source_kind=str(payload["image_source_kind"]) if payload.get("image_source_kind") is not None else None,
        image_content_type=str(payload["image_content_type"]) if payload.get("image_content_type") is not None else None,
        extraction_method=str(payload["extraction_method"]) if payload.get("extraction_method") is not None else None,
        source_spans=source_spans_from_dict(payload.get("source_spans", [])),
        quote_texts=raw_quotes,
    )


def parsed_image_asset_to_dict(asset: ParsedImageAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "source_kind": asset.source_kind,
        "object_path": asset.object_path,
        "content_type": asset.content_type,
        "content_hash": asset.content_hash,
        "page": asset.page,
        "bbox": list(asset.bbox) if asset.bbox is not None else None,
        "width": asset.width,
        "height": asset.height,
        "extracted_text": asset.extracted_text,
        "caption": asset.caption,
        "confidence": asset.confidence,
        "quality_flags": list(asset.quality_flags),
    }


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def source_spans_from_dict(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("source_spans must be a list")
    result = []
    for span in value:
        if not isinstance(span, dict) or type(span.get("page")) is not int or span["page"] < 1:
            raise ValueError("source span requires a positive page number")
        bbox = span.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not all(
            type(x) in {int, float} and math.isfinite(x) for x in bbox
        ) or bbox[2] < bbox[0] or bbox[3] < bbox[1]:
            raise ValueError("source span requires a valid bounding box")
        if not isinstance(span.get("exact_text"), str):
            raise ValueError("source span requires exact_text")
        result.append({"page": span["page"], "bbox": list(bbox), "exact_text": span["exact_text"]})
    return result
