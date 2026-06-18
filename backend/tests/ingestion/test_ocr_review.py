from __future__ import annotations

from rag_ingestion.parsers.models import ParsedPdfItem
from rag_ingestion.stages.steps import _low_confidence_ocr_items


def _ocr_item(*, confidence: float | None) -> ParsedPdfItem:
    return ParsedPdfItem(
        index=1,
        text="Recognized OCR text",
        item_type="text",
        page_start=1,
        page_end=1,
        confidence=confidence,
        quality_flags=["source:ocr", "docling_ocr"],
    )


def test_missing_ocr_confidence_does_not_force_human_review() -> None:
    assert _low_confidence_ocr_items([_ocr_item(confidence=None)], 0.9) == []


def test_explicit_low_ocr_confidence_requires_human_review() -> None:
    review_items = _low_confidence_ocr_items([_ocr_item(confidence=0.89)], 0.9)

    assert len(review_items) == 1
    assert review_items[0]["partial_text"] == "Recognized OCR text"


def test_explicit_high_ocr_confidence_skips_human_review() -> None:
    assert _low_confidence_ocr_items([_ocr_item(confidence=0.9)], 0.9) == []
