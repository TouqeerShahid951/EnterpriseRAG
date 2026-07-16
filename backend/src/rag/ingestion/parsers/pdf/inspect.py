"""Inspect parser output for a local PDF file."""

from __future__ import annotations

import argparse
from pathlib import Path

from rag.ingestion.chunking import chunk_items
from rag.ingestion.parsers.models import ParsedPdfItem
from rag.ingestion.parsers.pdf.pymupdf import parse_pymupdf_pdf

DEFAULT_CHUNK_TARGET_TOKENS = 512
DEFAULT_CHUNK_OVERLAP_TOKENS = 64
DEFAULT_PARENT_MAX_TOKENS = 2048


def main() -> int:
    args = _parser().parse_args()
    file_bytes = Path(args.pdf_path).read_bytes()
    items, page_count = parse_pymupdf_pdf(file_bytes)
    selected_items = _page_items(items, args.page)
    print(f"pdf_path={args.pdf_path}")
    print(f"page_count={page_count}")
    print(f"item_count={len(items)}")
    if args.page:
        print(f"selected_page={args.page}")
        print(f"selected_item_count={len(selected_items)}")
    if args.show_items:
        _print_items(selected_items)
    if args.show_chunks:
        _print_chunks(selected_items)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect AgenticRAG PDF parser output.")
    parser.add_argument("pdf_path")
    parser.add_argument("--page", type=int)
    parser.add_argument("--show-items", action="store_true")
    parser.add_argument("--show-chunks", action="store_true")
    return parser


def _page_items(items: list[ParsedPdfItem], page: int | None) -> list[ParsedPdfItem]:
    if page is None:
        return items
    return [
        item
        for item in items
        if (item.page_start or 0) <= page <= (item.page_end or item.page_start or 0)
    ]


def _print_items(items: list[ParsedPdfItem]) -> None:
    for item in items:
        print(
            "item "
            f"index={item.index} "
            f"type={item.item_type} "
            f"pages={_pages(item.page_start, item.page_end)} "
            f"section={_clean(item.section_title)} "
            f"text={_preview(item.text)}"
        )


def _print_chunks(items: list[ParsedPdfItem]) -> None:
    chunks = chunk_items(
        items,
        doc_id="inspect",
        target_tokens=DEFAULT_CHUNK_TARGET_TOKENS,
        overlap_tokens=DEFAULT_CHUNK_OVERLAP_TOKENS,
        parent_max_tokens=DEFAULT_PARENT_MAX_TOKENS,
    )
    print(f"chunk_count={len(chunks)}")
    for chunk in chunks:
        print(
            "chunk "
            f"index={chunk.index} "
            f"type={chunk.chunk_type} "
            f"pages={_pages(chunk.page_start, chunk.page_end)} "
            f"section={_clean(chunk.section_title)} "
            f"text={_preview(chunk.text)}"
        )


def _pages(start: int | None, end: int | None) -> str:
    if start is None:
        return "unknown"
    return str(start) if end in {None, start} else f"{start}-{end}"


def _preview(text: str) -> str:
    return _clean(text)[:240]


def _clean(value: str | None) -> str:
    return " ".join(str(value or "").split())


if __name__ == "__main__":
    raise SystemExit(main())
