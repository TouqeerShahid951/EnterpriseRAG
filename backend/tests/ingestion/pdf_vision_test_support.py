from __future__ import annotations

from io import BytesIO

from rag.ingestion.parsers.models import DocumentParseResult, ParsedPdfItem


class DummyStore:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, bytes, str]] = []

    def put_image_asset(self, *, doc_id, asset_id, filename, content, content_type):
        self.saved.append((doc_id, asset_id, filename, content, content_type))
        return f"memory://{asset_id}/{filename}"


class DummyAnalyzer:
    pass


def jpeg_bytes(width: int, height: int) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), color="white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def image_size(content: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        return image.size


def complex_layout_result() -> DocumentParseResult:
    item = ParsedPdfItem(
        index=0,
        text="Right column second. Left column first. Witness statement.",
        item_type="text",
        page_start=1,
        page_end=1,
        parser="docling",
        quality_flags=[
            "source:docling_layout",
            "multi_column_layout",
            "reading_order_ambiguous",
        ],
    )
    return DocumentParseResult(
        items=[item],
        provenance={
            "document_kind": "pdf",
            "primary_parser": "layered",
            "secondary_parser": "docling",
            "routing_mode": "quality_selected_docling",
            "parser_item_counts": {"docling": 1},
            "parser_page_counts": {"docling": 1},
            "quality_flag_counts": {
                "multi_column_layout": 1,
                "reading_order_ambiguous": 1,
            },
        },
    )


def text_result(text: str, *, bbox=None) -> DocumentParseResult:
    item = ParsedPdfItem(
        index=0,
        text=text,
        item_type="text",
        page_start=1,
        page_end=1,
        parser="docling",
        quality_flags=["source:docling"],
        bbox=bbox,
    )
    return DocumentParseResult(
        items=[item],
        provenance={
            "document_kind": "pdf",
            "primary_parser": "layered",
            "secondary_parser": "docling",
            "routing_mode": "quality_selected_docling",
            "parser_item_counts": {"docling": 1},
            "parser_page_counts": {"docling": 1},
            "quality_flag_counts": {"source:docling": 1},
        },
    )


def text_items_result(
    entries: list[tuple[str, tuple[float, float, float, float]]],
) -> DocumentParseResult:
    items = [
        ParsedPdfItem(
            index=index,
            text=text,
            item_type="text",
            page_start=1,
            page_end=1,
            parser="docling",
            quality_flags=["source:docling"],
            bbox=bbox,
        )
        for index, (text, bbox) in enumerate(entries)
    ]
    return DocumentParseResult(
        items=items,
        provenance={
            "document_kind": "pdf",
            "primary_parser": "layered",
            "secondary_parser": "docling",
            "routing_mode": "quality_selected_docling",
            "parser_item_counts": {"docling": len(items)},
            "parser_page_counts": {"docling": 1},
            "quality_flag_counts": {"source:docling": len(items)},
        },
    )
