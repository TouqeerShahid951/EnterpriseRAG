"""Word (DOCX) parsing and embedded-image extraction."""

from __future__ import annotations

from collections.abc import Callable

from rag.ingestion.errors import UnsupportedDocumentError, WorkerStepError
from rag.ingestion.parsers.docling.adapter import parse_docling_docx
from rag.ingestion.parsers.hierarchy import apply_hierarchy
from rag.ingestion.parsers.images import (
    ImageAnalyzer,
    ImageAssetStore,
    ImageProgressCallback,
    docx_image_sources,
    image_sources_to_items,
)
from rag.ingestion.parsers.models import (
    DocumentParseResult,
    ParsedImageAsset,
    ParsedPdfItem,
)
from rag.ingestion.parsers.pdf.image_processing import renumber_items
from rag.ingestion.parsers.provenance import base_report

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
ImageItemsFactory = Callable[
    ..., tuple[list[ParsedPdfItem], list[ParsedImageAsset]]
]


def parse_word_document(
    file_bytes: bytes,
    *,
    image_context: tuple[str, ImageAssetStore, ImageAnalyzer] | None = None,
    image_items_factory: ImageItemsFactory = image_sources_to_items,
    image_progress_callback: ImageProgressCallback | None = None,
) -> DocumentParseResult:
    items = validated_docx_items(file_bytes)
    image_assets: list[ParsedImageAsset] = []
    if image_context is not None:
        image_items, image_assets = image_items_factory(
            docx_image_sources(file_bytes),
            doc_id=image_context[0],
            store=image_context[1],
            analyzer=image_context[2],
            start_index=len(items),
            progress_callback=image_progress_callback,
        )
        items = renumber_items([*items, *image_items])
    return DocumentParseResult(
        items=items,
        provenance=base_report(
            document_kind="docx",
            page_count=None,
            primary_parser="docling",
            secondary_parser="vision" if image_context is not None else None,
            routing_mode="docling_docx",
            config={},
            items=items,
        )
        | {"image_asset_count": len(image_assets)},
        assets=image_assets,
    )


def validated_docx_items(file_bytes: bytes) -> list[ParsedPdfItem]:
    try:
        items = parse_docling_docx(file_bytes)
    except ImportError as exc:
        raise WorkerStepError(
            "docx_dependency_missing", "Docling DOCX dependency is not installed."
        ) from exc
    except Exception as exc:
        raise WorkerStepError(
            "docx_parse_failed", "Docling failed to parse DOCX."
        ) from exc
    if not items or not "".join(item.text for item in items).strip():
        raise UnsupportedDocumentError()
    return apply_hierarchy(renumber_items(items))
