"""Format-specific extraction for glossary sources, independent of RAG indexing."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rag.ingestion.parsers.docling.adapter import parse_docling_pdf
from rag.ingestion.parsers.spreadsheet import XLSX_CONTENT_TYPE, parse_spreadsheet_document
from rag.shared.contracts.abbreviations import (
    abbreviation_entry_candidates,
    abbreviation_entry_failure_reason,
    normalize_abbreviation_entry,
)


PDF_CONTENT_TYPE = "application/pdf"
_HEADER_RE = re.compile(
    r"^\s*(?:short words?|abbreviations?|acronyms?|codes?)\s+"
    r"(?:full expressions?|full forms?|expansions?|meanings?|definitions?)\s*$",
    re.IGNORECASE,
)
_ROW_RE = re.compile(r"^\s*([A-Z][A-Z0-9./&-]{1,19})\s+(.{2,240}?)\s*$")
_TABLE_ROW_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9./&-]{1,19})\s+(.{2,240}?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GlossarySourceExtraction:
    entries: tuple[tuple[str, str, int | None], ...]
    rejected_entries: tuple[dict[str, object], ...]


def extract_glossary_source(
    content: bytes,
    *,
    content_type: str,
    filename: str,
) -> GlossarySourceExtraction:
    """Extract the first-two-column glossary table from a PDF or XLSX source."""
    if content_type == PDF_CONTENT_TYPE:
        items = parse_docling_pdf(content)
    elif content_type == XLSX_CONTENT_TYPE:
        items = parse_spreadsheet_document(
            content,
            content_type=content_type,
            file_path=filename,
        ).items
    else:
        raise ValueError("Glossary sources must be a PDF or XLSX file.")
    return _entries_from_items(items)


def _entries_from_items(items: list[object]) -> GlossarySourceExtraction:
    entries: dict[tuple[str, str], tuple[str, str, int | None]] = {}
    rejected: list[dict[str, object]] = []
    for item in items:
        text = str(getattr(item, "text", ""))
        fields = getattr(item, "structured_fields", [])
        page = getattr(item, "page_start", None) or getattr(item, "page", None)
        page_number = page if isinstance(page, int) and page > 0 else None
        pairs = abbreviation_entry_candidates(text, fields)
        lines = text.splitlines()
        table_pairs = _markdown_table_pairs(lines)
        pairs.extend(table_pairs)
        if not table_pairs and not text.lstrip().startswith("Table "):
            row_pattern = _TABLE_ROW_RE if getattr(item, "chunk_type", "") == "table" else _ROW_RE
            for line in lines:
                if _HEADER_RE.fullmatch(line):
                    continue
                match = row_pattern.fullmatch(line)
                if match and match[2][0] not in "—–-:=":
                    pairs.append((match[1], match[2]))
        for raw_abbreviation, raw_expansion in dict.fromkeys(pairs):
            reason = abbreviation_entry_failure_reason(raw_abbreviation, raw_expansion)
            if reason is not None:
                _record_rejection(rejected, raw_abbreviation, page_number, reason)
                continue
            abbreviation, expansion = normalize_abbreviation_entry(raw_abbreviation, raw_expansion)
            entries.setdefault(
                (abbreviation.casefold(), expansion.casefold()),
                (abbreviation, expansion, page_number),
            )
    return GlossarySourceExtraction(tuple(entries.values()), tuple(rejected))


def _markdown_table_pairs(lines: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [" ".join(cell.split()) for cell in stripped.strip("|").split("|")]
        if len(cells) != 2 or _HEADER_RE.fullmatch(" ".join(cells)):
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        pairs.append((cells[0], cells[1]))
    return pairs


def _record_rejection(
    rejected: list[dict[str, object]],
    abbreviation: str,
    page: int | None,
    reason: str,
) -> None:
    term = " ".join(abbreviation.split())[:20]
    record: dict[str, object] = {"term": term, "page": page, "reason": reason}
    if term and record not in rejected and len(rejected) < 20:
        rejected.append(record)
