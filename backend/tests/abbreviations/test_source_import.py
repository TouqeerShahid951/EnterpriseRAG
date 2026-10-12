from types import SimpleNamespace

from rag.abbreviations import source_import


def test_pdf_glossary_source_uses_docling_table_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        source_import,
        "parse_docling_pdf",
        lambda _content: [
            SimpleNamespace(
                text="",
                structured_fields=[
                    {"label": "Short Word", "value": "tdn"},
                    {"label": "Full expression", "value": "Tradesman"},
                ],
                page_start=3,
            )
        ],
    )

    extracted = source_import.extract_glossary_source(
        b"pdf",
        content_type=source_import.PDF_CONTENT_TYPE,
        filename="terms.pdf",
    )

    assert extracted.entries == (("TDN", "Tradesman", 3),)
    assert extracted.rejected_entries == ()


def test_glossary_source_reports_rejected_term(monkeypatch) -> None:
    monkeypatch.setattr(
        source_import,
        "parse_docling_pdf",
        lambda _content: [
            SimpleNamespace(text="ABC — ABC", structured_fields=[], page_start=2)
        ],
    )

    extracted = source_import.extract_glossary_source(
        b"pdf",
        content_type=source_import.PDF_CONTENT_TYPE,
        filename="terms.pdf",
    )

    assert extracted.entries == ()
    assert extracted.rejected_entries == (
        {
            "term": "ABC",
            "page": 2,
            "reason": "full expression matches the abbreviation",
        },
    )


def test_pdf_glossary_source_recovers_flattened_case_insensitive_table_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        source_import,
        "parse_docling_pdf",
        lambda _content: [
            SimpleNamespace(
                text="Short Word Full Expression\nabvn Abbreviation\nTDN Tradesman",
                structured_fields=[],
                page_start=1,
                chunk_type="table",
            )
        ],
    )

    extracted = source_import.extract_glossary_source(
        b"pdf",
        content_type=source_import.PDF_CONTENT_TYPE,
        filename="terms.pdf",
    )

    assert extracted.entries == (
        ("ABVN", "Abbreviation", 1),
        ("TDN", "Tradesman", 1),
    )


def test_pdf_glossary_source_preserves_spaced_short_words_from_markdown_table(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        source_import,
        "parse_docling_pdf",
        lambda _content: [
            SimpleNamespace(
                text=(
                    "| Short Word | Full Expression |\n"
                    "| --- | --- |\n"
                    "| spec ops | Special operations |\n"
                    "| psy ops | Psychological operations |"
                ),
                structured_fields=[],
                page_start=1,
            )
        ],
    )

    extracted = source_import.extract_glossary_source(
        b"pdf",
        content_type=source_import.PDF_CONTENT_TYPE,
        filename="terms.pdf",
    )

    assert extracted.entries == (
        ("SPEC OPS", "Special operations", 1),
        ("PSY OPS", "Psychological operations", 1),
    )
    assert extracted.rejected_entries == ()
