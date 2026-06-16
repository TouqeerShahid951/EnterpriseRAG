"""Bounded parser provenance reports for ingestion jobs."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .models import ParsedPdfItem

PROVENANCE_VERSION = 1
PAGE_LIST_LIMIT = 50


def parser_item_counts(items: list[ParsedPdfItem]) -> dict[str, int]:
    return dict(sorted(Counter(item.parser for item in items).items()))


def parser_page_counts(items: list[ParsedPdfItem]) -> dict[str, int]:
    pages_by_parser: dict[str, set[int]] = {}
    for item in items:
        if item.page_start is None:
            continue
        pages_by_parser.setdefault(item.parser, set()).add(item.page_start)
    return {parser: len(pages) for parser, pages in sorted(pages_by_parser.items())}


def quality_flag_counts(items: list[ParsedPdfItem]) -> dict[str, int]:
    return dict(sorted(Counter(flag for item in items for flag in item.quality_flags).items()))


def base_report(
    *,
    document_kind: str,
    page_count: int | None,
    primary_parser: str,
    secondary_parser: str | None,
    routing_mode: str,
    config: dict[str, Any],
    items: list[ParsedPdfItem],
    docling_selection: dict[str, Any] | None = None,
    fallback: dict[str, Any] | None = None,
    errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "version": PROVENANCE_VERSION,
        "document_kind": document_kind,
        "page_count": page_count,
        "primary_parser": primary_parser,
        "secondary_parser": secondary_parser,
        "routing_mode": routing_mode,
        "config": dict(config),
        "docling_selection": docling_selection,
        "parser_item_counts": parser_item_counts(items),
        "parser_page_counts": parser_page_counts(items),
        "quality_flag_counts": quality_flag_counts(items),
        "fallback": fallback,
        "errors": list(errors or []),
    }


def bounded_page_report(pages: list[dict[str, Any]]) -> dict[str, Any]:
    bounded = pages[:PAGE_LIST_LIMIT]
    return {
        "total": len(pages),
        "truncated": len(pages) > PAGE_LIST_LIMIT,
        "items": bounded,
    }


def weak_page_entry(page: Any) -> dict[str, Any]:
    return {
        "page_no": int(page.page_no),
        "score": int(page.score),
        "reasons": [str(flag) for flag in page.flags],
    }
