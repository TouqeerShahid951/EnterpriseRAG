from __future__ import annotations

import pytest

from rag.ingestion.parsers.document import parse_document
from rag.ingestion.parsers.models import ParsedPdfItem
from rag.ingestion.parsers.word import DOCX_CONTENT_TYPE
from rag.ingestion.parsers.word import parser as word_parser


def test_docx_dispatch_uses_word_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        word_parser,
        "parse_docling_docx",
        lambda _file_bytes: [
            ParsedPdfItem(
                index=7,
                text="Service manual",
                item_type="text",
                page_start=None,
                page_end=None,
                parser="docling",
            )
        ],
    )

    parsed = parse_document(
        b"docx package bytes",
        content_type=DOCX_CONTENT_TYPE,
        file_path="manual.docx",
        min_chars_per_page=10,
    )

    assert [item.index for item in parsed.items] == [0]
    assert parsed.provenance["document_kind"] == "docx"
    assert parsed.provenance["routing_mode"] == "docling_docx"
