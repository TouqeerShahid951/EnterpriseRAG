"""Layered PDF parser that fuses structured layout with native extraction."""

from __future__ import annotations

from dataclasses import replace

from .docling_adapter import parse_docling_pdf
from .docling_repairs import merge_docling_repairs
from .hierarchy import apply_hierarchy
from .models import DocumentParseResult, ParsedPdfItem
from .provenance import base_report, bounded_page_report, weak_page_entry
from .pymupdf import PageProgressCallback, PymuPDFParseResult, parse_pymupdf_pdf_with_metadata
from .quality import WeakPage, annotate_item_quality, ocr_candidate_pages, score_weak_pages, weak_page_ratio

DOCLING_COVERAGE_RATIO = 0.75
WHOLE_PAGE_REPAIR_FLAGS = {
    "image_only_page",
    "scanned_or_handwritten_candidate",
    "rotated_page",
    "invoice_like_layout",
}


def parse_layered_pdf(
    file_bytes: bytes,
    *,
    min_chars_per_page: int,
    weak_page_threshold: int,
    full_doc_weak_page_ratio: float,
    max_docling_pages: int,
    docling_batch_pages: int,
    page_progress_callback: PageProgressCallback | None = None,
) -> DocumentParseResult:
    baseline = parse_pymupdf_pdf_with_metadata(file_bytes, page_progress_callback=page_progress_callback)
    config = {
        "min_chars_per_page": min_chars_per_page,
        "weak_page_threshold": weak_page_threshold,
        "full_doc_weak_page_ratio": full_doc_weak_page_ratio,
        "max_docling_pages": max_docling_pages,
        "docling_batch_pages": docling_batch_pages,
    }
    baseline_items = _baseline_items(baseline)
    weak_pages = score_weak_pages(
        baseline_items,
        page_count=baseline.page_count,
        threshold=weak_page_threshold,
        page_quality_flags=baseline.page_quality_flags,
    )
    selected_pages = _selected_docling_pages(
        weak_pages,
        page_count=baseline.page_count,
        max_docling_pages=max_docling_pages,
    )
    if selected_pages == set():
        return _result(
            _ambiguous_native_pages(baseline_items, baseline),
            baseline=baseline,
            weak_pages=weak_pages,
            selected_pages=selected_pages,
            routing_mode="native_only",
            config=config,
        )

    try:
        docling_items = parse_docling_pdf(
            file_bytes,
            pages=selected_pages,
            allow_page_repair=False,
            page_batch_size=docling_batch_pages,
        )
    except ImportError:
        items = _with_flags(_ambiguous_native_pages(baseline_items, baseline), {"docling_unavailable"})
        return _result(
            items,
            baseline=baseline,
            weak_pages=weak_pages,
            selected_pages=selected_pages,
            routing_mode="native_fallback",
            config=config,
            fallback={"from": "docling", "to": "pymupdf", "reason": "docling_unavailable"},
            errors=[{"component": "docling", "code": "ImportError"}],
        )
    except Exception as exc:
        items = _with_flags(
            _ambiguous_native_pages(baseline_items, baseline),
            {f"docling_layout_failed:{type(exc).__name__}"},
        )
        return _result(
            items,
            baseline=baseline,
            weak_pages=weak_pages,
            selected_pages=selected_pages,
            routing_mode="native_fallback",
            config=config,
            fallback={"from": "docling", "to": "pymupdf", "reason": "docling_layout_failed"},
            errors=[{"component": "docling", "code": type(exc).__name__}],
        )

    repair_failure_pages: set[int] = set()
    repair_failure_flags: set[str] = set()
    if _needs_docling_page_repair(baseline_items, weak_pages, baseline.page_count, full_doc_weak_page_ratio):
        docling_items, repair_failure_pages, repair_failure_flags = _add_page_repairs(
            file_bytes,
            docling_items,
            weak_pages,
            page_count=baseline.page_count,
            has_baseline_items=bool(baseline_items),
            full_doc_weak_page_ratio=full_doc_weak_page_ratio,
            candidate_pages=selected_pages,
            docling_batch_pages=docling_batch_pages,
        )

    fused = _fuse_pages(
        baseline,
        baseline_items,
        docling_items,
        weak_pages=weak_pages,
        min_chars_per_page=min_chars_per_page,
    )
    if _has_missing_docling_provenance(docling_items):
        fused = _with_flags(fused, {"missing_item_provenance"})
    if repair_failure_flags:
        fused = _with_flags_for_pages(fused, repair_failure_pages, repair_failure_flags)
    skipped_pages = set() if selected_pages is None else {page.page_no for page in weak_pages} - selected_pages
    if skipped_pages:
        fused = _with_flags_for_pages(fused, skipped_pages, {"docling_page_budget_exceeded"})
    items = apply_hierarchy(_renumber_items(fused))
    errors = [{"component": "docling_page_repair", "code": flag} for flag in sorted(repair_failure_flags)]
    return _result(
        items,
        baseline=baseline,
        weak_pages=weak_pages,
        selected_pages=selected_pages,
        routing_mode="full_document_docling" if selected_pages is None else "quality_selected_docling",
        config=config,
        errors=errors,
    )


def _baseline_items(baseline: PymuPDFParseResult) -> list[ParsedPdfItem]:
    return annotate_item_quality(apply_hierarchy(baseline.items), baseline.page_text_chars, baseline.page_quality_flags)


def _needs_docling_page_repair(
    baseline_items: list[ParsedPdfItem],
    weak_pages: list[WeakPage],
    page_count: int,
    full_doc_weak_page_ratio: float,
) -> bool:
    if not weak_pages:
        return False
    if not baseline_items:
        return True
    if weak_page_ratio(weak_pages, page_count) >= full_doc_weak_page_ratio:
        return any(_needs_whole_page_repair(page) for page in weak_pages)
    return any(_needs_whole_page_repair(page) for page in weak_pages)


def _add_page_repairs(
    file_bytes: bytes,
    docling_items: list[ParsedPdfItem],
    weak_pages: list[WeakPage],
    *,
    page_count: int,
    has_baseline_items: bool,
    full_doc_weak_page_ratio: float,
    candidate_pages: set[int] | None,
    docling_batch_pages: int,
) -> tuple[list[ParsedPdfItem], set[int], set[str]]:
    repair_pages = _docling_repair_pages(
        weak_pages,
        page_count=page_count,
        full_doc_weak_page_ratio=full_doc_weak_page_ratio,
        has_baseline_items=has_baseline_items,
    )
    if candidate_pages is not None:
        repair_pages &= candidate_pages
    if not repair_pages:
        return docling_items, set(), set()
    try:
        repairs = _parse_docling_repairs(
            file_bytes,
            repair_pages=repair_pages,
            weak_pages=weak_pages,
            docling_batch_pages=docling_batch_pages,
        )
    except Exception as exc:
        return docling_items, repair_pages, {
            "docling_page_repair_unavailable",
            f"docling_page_repair_failed:{type(exc).__name__}",
        }
    existing = {
        (item.page_start, item.item_type, item.text): index
        for index, item in enumerate(docling_items)
    }
    merged = [*docling_items]
    for item in repairs:
        key = (item.page_start, item.item_type, item.text)
        existing_index = existing.get(key)
        if existing_index is None:
            existing[key] = len(merged)
            merged.append(item)
            continue
        current = merged[existing_index]
        merged[existing_index] = replace(
            current,
            quality_flags=sorted({*current.quality_flags, *item.quality_flags}),
            confidence=item.confidence if item.confidence is not None else current.confidence,
        )
    return _renumber_items(merged), set(), set()


def _parse_docling_repairs(
    file_bytes: bytes,
    *,
    repair_pages: set[int],
    weak_pages: list[WeakPage],
    docling_batch_pages: int,
) -> list[ParsedPdfItem]:
    ocr_pages = repair_pages & ocr_candidate_pages(weak_pages)
    layout_pages = repair_pages - ocr_pages
    repairs: list[ParsedPdfItem] = []
    if layout_pages:
        repairs.extend(
            parse_docling_pdf(
                file_bytes,
                pages=layout_pages,
                allow_page_repair=True,
                page_batch_size=docling_batch_pages,
            )
        )
    if ocr_pages:
        repairs.extend(
            parse_docling_pdf(
                file_bytes,
                pages=ocr_pages,
                allow_page_repair=True,
                mark_ocr=True,
                page_batch_size=docling_batch_pages,
            )
        )
    return _renumber_items(sorted(repairs, key=lambda item: (item.page_start or 0, item.index)))


def _docling_repair_pages(
    weak_pages: list[WeakPage],
    *,
    page_count: int,
    full_doc_weak_page_ratio: float,
    has_baseline_items: bool,
) -> set[int]:
    if not has_baseline_items and weak_page_ratio(weak_pages, page_count) >= full_doc_weak_page_ratio:
        return set(range(1, page_count + 1))
    return {page.page_no for page in weak_pages if _needs_whole_page_repair(page)}


def _selected_docling_pages(
    weak_pages: list[WeakPage],
    *,
    page_count: int,
    max_docling_pages: int,
) -> set[int] | None:
    if page_count <= max_docling_pages:
        return None
    ranked = sorted(weak_pages, key=lambda page: (-page.score, page.page_no))
    return {page.page_no for page in ranked[:max_docling_pages]}


def _result(
    items: list[ParsedPdfItem],
    *,
    baseline: PymuPDFParseResult,
    weak_pages: list[WeakPage],
    selected_pages: set[int] | None,
    routing_mode: str,
    config: dict[str, object],
    fallback: dict[str, str] | None = None,
    errors: list[dict[str, str]] | None = None,
) -> DocumentParseResult:
    weak_by_page = {page.page_no: page for page in weak_pages}
    if selected_pages is None:
        selected_entries = [weak_page_entry(page) for page in sorted(weak_pages, key=lambda page: page.page_no)]
        skipped_entries: list[dict[str, object]] = []
        selection_mode = "all_pages_within_budget"
    else:
        selected_entries = [
            weak_page_entry(weak_by_page[page_no])
            for page_no in sorted(selected_pages)
            if page_no in weak_by_page
        ]
        skipped_entries = [
            weak_page_entry(page)
            for page in sorted(weak_pages, key=lambda page: page.page_no)
            if page.page_no not in selected_pages
        ]
        selection_mode = "quality_selected"
    report = base_report(
        document_kind="pdf",
        page_count=baseline.page_count,
        primary_parser="layered",
        secondary_parser="docling",
        routing_mode=routing_mode,
        config=config,
        items=items,
        docling_selection={
            "mode": selection_mode,
            "budget_pages": config["max_docling_pages"],
            "batch_pages": config["docling_batch_pages"],
            "weak_pages_total": len(weak_pages),
            "selected_pages": bounded_page_report(selected_entries),
            "skipped_pages": bounded_page_report(skipped_entries),
        },
        fallback=fallback,
        errors=errors,
    )
    return DocumentParseResult(items=items, provenance=report)


def _fuse_pages(
    baseline: PymuPDFParseResult,
    baseline_items: list[ParsedPdfItem],
    docling_items: list[ParsedPdfItem],
    *,
    weak_pages: list[WeakPage],
    min_chars_per_page: int,
) -> list[ParsedPdfItem]:
    pageful_docling = [item for item in docling_items if item.page_start is not None]
    repaired_baseline = merge_docling_repairs(baseline_items, pageful_docling, weak_pages) if weak_pages else baseline_items
    baseline_by_page = _items_by_page(repaired_baseline, baseline.page_count)
    docling_by_page = _items_by_page(pageful_docling, baseline.page_count)
    fused: list[ParsedPdfItem] = []
    for page_no in range(1, baseline.page_count + 1):
        page_docling = docling_by_page.get(page_no, [])
        page_baseline = baseline_by_page.get(page_no, [])
        if _use_docling_page(page_docling, page_baseline, baseline, page_no, min_chars_per_page):
            fused.extend(page_docling)
            continue
        fused.extend(_mark_ambiguous_page(page_baseline, baseline.page_quality_flags.get(page_no, [])))
    if fused:
        return fused
    return pageful_docling or repaired_baseline


def _use_docling_page(
    docling_items: list[ParsedPdfItem],
    baseline_items: list[ParsedPdfItem],
    baseline: PymuPDFParseResult,
    page_no: int,
    min_chars_per_page: int,
) -> bool:
    if not docling_items:
        return False
    if not _provenance_complete(docling_items):
        return False
    docling_chars = _content_chars(docling_items)
    if docling_chars < max(1, min_chars_per_page):
        return False
    native_chars = baseline.page_text_chars.get(page_no, 0)
    if native_chars <= 0:
        return True
    if docling_chars < int(native_chars * DOCLING_COVERAGE_RATIO):
        return False
    if "multi_column_layout" in baseline.page_quality_flags.get(page_no, []):
        return True
    return bool(baseline_items) or docling_chars >= min_chars_per_page


def _provenance_complete(items: list[ParsedPdfItem]) -> bool:
    return all(item.page_start is not None and item.bbox is not None for item in items if item.item_type != "figure")


def _content_chars(items: list[ParsedPdfItem]) -> int:
    return sum(len(item.text) for item in items if item.item_type in {"heading", "text", "caption", "table"})


def _items_by_page(items: list[ParsedPdfItem], page_count: int) -> dict[int, list[ParsedPdfItem]]:
    grouped: dict[int, list[ParsedPdfItem]] = {page_no: [] for page_no in range(1, page_count + 1)}
    for item in items:
        if item.page_start is None:
            continue
        grouped.setdefault(item.page_start, []).append(item)
    return grouped


def _needs_whole_page_repair(weak_page: WeakPage) -> bool:
    return any(flag in WHOLE_PAGE_REPAIR_FLAGS for flag in weak_page.flags)


def _ambiguous_native_pages(items: list[ParsedPdfItem], baseline: PymuPDFParseResult) -> list[ParsedPdfItem]:
    return [
        replace(item, quality_flags=sorted({*item.quality_flags, "reading_order_ambiguous"}))
        if "multi_column_layout" in baseline.page_quality_flags.get(item.page_start or 0, [])
        else item
        for item in items
    ]


def _mark_ambiguous_page(items: list[ParsedPdfItem], page_flags: list[str]) -> list[ParsedPdfItem]:
    if "multi_column_layout" not in page_flags:
        return items
    return _with_flags(items, {"reading_order_ambiguous"})


def _has_missing_docling_provenance(items: list[ParsedPdfItem]) -> bool:
    return any("missing_item_provenance" in item.quality_flags for item in items)


def _with_flags(items: list[ParsedPdfItem], flags: set[str]) -> list[ParsedPdfItem]:
    if not flags:
        return items
    return [replace(item, quality_flags=sorted({*item.quality_flags, *flags})) for item in items]


def _with_flags_for_pages(items: list[ParsedPdfItem], pages: set[int], flags: set[str]) -> list[ParsedPdfItem]:
    if not pages or not flags:
        return items
    return [
        replace(item, quality_flags=sorted({*item.quality_flags, *flags}))
        if item.page_start in pages
        else item
        for item in items
    ]


def _renumber_items(items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    return [replace(item, index=index) for index, item in enumerate(items)]
