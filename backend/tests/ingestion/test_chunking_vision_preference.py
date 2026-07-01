from __future__ import annotations

from rag_ingestion.chunking import chunk_items
from rag_ingestion.parsers.models import ParsedPdfItem


def test_low_confidence_docling_ocr_table_rows_are_suppressed_when_vision_ocr_covers_page() -> None:
    chunks = chunk_items(
        [
            _docling_ocr_table(confidence=None),
            ParsedPdfItem(
                index=2,
                text=(
                    "Visible image text:\n"
                    "No.\tName\tService No\tJob Title\n"
                    "O1\tW.D.Rayjan Prugandha\t008249\tTech.Mugor/ORAOM\n\n"
                    "Image description:\n"
                    "A handwritten table of names, service numbers, and job titles."
                ),
                item_type="image_text",
                page_start=1,
                page_end=1,
                parser="pdf_image",
                quality_flags=["source:ocr", "source:pdf_image", "source:vision"],
                confidence=0.95,
            ),
        ],
        doc_id="doc-1",
        target_tokens=128,
        overlap_tokens=0,
        parent_max_tokens=512,
    )

    assert [chunk.chunk_type for chunk in chunks] == ["table", "text"]
    assert not any(chunk.chunk_type == "table_row" for chunk in chunks)
    assert "W.D.Rayjan Prugandha" in chunks[1].text


def test_docling_ocr_table_rows_remain_without_vision_ocr_page_coverage() -> None:
    chunks = chunk_items(
        [_docling_ocr_table(confidence=None)],
        doc_id="doc-1",
        target_tokens=128,
        overlap_tokens=0,
        parent_max_tokens=512,
    )

    assert any(chunk.chunk_type == "table_row" for chunk in chunks)


def test_native_table_rows_remain_when_page_has_vision_ocr() -> None:
    chunks = chunk_items(
        [
            ParsedPdfItem(
                index=1,
                text="| Name | Service No |\n| --- | --- |\n| Asha | 123 |",
                item_type="table",
                page_start=1,
                page_end=1,
                parser="pymupdf",
                quality_flags=["source:pymupdf_native"],
                confidence=0.95,
            ),
            ParsedPdfItem(
                index=2,
                text="Visible image text:\nLogo text",
                item_type="image_text",
                page_start=1,
                page_end=1,
                parser="pdf_image",
                quality_flags=["source:ocr", "source:pdf_image", "source:vision"],
                confidence=0.95,
            ),
        ],
        doc_id="doc-1",
        target_tokens=128,
        overlap_tokens=0,
        parent_max_tokens=512,
    )

    assert any(chunk.chunk_type == "table_row" for chunk in chunks)


def _docling_ocr_table(*, confidence: float | None) -> ParsedPdfItem:
    return ParsedPdfItem(
        index=1,
        text=(
            "| No. | Name | Service No | Job Title |\n"
            "| --- | --- | --- | --- |\n"
            "| 10 | 6+800 | 008249 | Tech.Mug ORa |\n"
            "| 02 | H.C.Jayawter | 00830 | T.OR |"
        ),
        item_type="table",
        page_start=1,
        page_end=1,
        parser="docling",
        quality_flags=[
            "docling_ocr",
            "docling_table_repair",
            "docling_table_repaired",
            "source:docling_layout",
            "source:ocr",
        ],
        confidence=confidence,
    )
