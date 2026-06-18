"""Layered PDF parsing entrypoint and native-text validation."""

from __future__ import annotations

from ..errors import UnsupportedPdfError
from .docling_adapter import DoclingProgressCallback
from .layered import parse_layered_pdf
from .models import DocumentParseResult, ParsedPdfItem
from .pymupdf import PageProgressCallback

DEFAULT_WEAK_PAGE_THRESHOLD = 5
DEFAULT_FULL_DOC_WEAK_PAGE_RATIO = 0.25


def parse_pdf_document(
    file_bytes: bytes,
    *,
    min_chars_per_page: int,
    weak_page_threshold: int = DEFAULT_WEAK_PAGE_THRESHOLD,
    full_doc_weak_page_ratio: float = DEFAULT_FULL_DOC_WEAK_PAGE_RATIO,
    layered_docling_max_pages: int = 40,
    layered_docling_batch_pages: int = 4,
    page_progress_callback: PageProgressCallback | None = None,
    docling_progress_callback: DoclingProgressCallback | None = None,
) -> DocumentParseResult:
    result = parse_layered_pdf(
        file_bytes,
        min_chars_per_page=min_chars_per_page,
        weak_page_threshold=weak_page_threshold,
        full_doc_weak_page_ratio=full_doc_weak_page_ratio,
        max_docling_pages=layered_docling_max_pages,
        docling_batch_pages=layered_docling_batch_pages,
        page_progress_callback=page_progress_callback,
        docling_progress_callback=docling_progress_callback,
    )
    items = result.items
    page_count = int(result.provenance.get("page_count") or 0)
    _validate_native_text(items, min_chars_per_page=min_chars_per_page, page_count=page_count)
    return result


def _validate_native_text(items: list[ParsedPdfItem], *, min_chars_per_page: int, page_count: int | None) -> None:
    if not items:
        raise UnsupportedPdfError()
    measured_pages = page_count or _page_count_from_items(items)
    total_chars = sum(len(item.text) for item in items)
    if total_chars < max(1, min_chars_per_page) * measured_pages:
        raise UnsupportedPdfError()


def _page_count_from_items(items: list[ParsedPdfItem]) -> int:
    pages = {
        page
        for item in items
        for page in (item.page_start, item.page_end)
        if isinstance(page, int) and page > 0
    }
    return max(1, len(pages))
