from __future__ import annotations

from rag.shared.ingestion_quality import parser_tuning_for_quality_preset
from rag_ingestion.parsers.layered import _selected_docling_pages
from rag_ingestion.parsers.quality import WeakPage


def test_fast_profile_caps_docling_to_small_page_budget() -> None:
    tuning = parser_tuning_for_quality_preset(
        "fast",
        weak_page_threshold=5,
        full_doc_weak_page_ratio=0.25,
        layered_docling_max_pages=40,
    )

    assert tuning.weak_page_threshold == 8
    assert tuning.layered_docling_max_pages == 12
    assert tuning.layered_docling_max_page_ratio == 0.10
    assert tuning.prefer_full_document_docling is False


def test_balanced_profile_uses_page_level_docling_for_clean_short_pdf() -> None:
    selected = _selected_docling_pages(
        [],
        page_count=20,
        max_docling_pages=40,
        max_docling_page_ratio=0.25,
        full_doc_weak_page_ratio=0.25,
        prefer_full_document_docling=False,
    )

    assert selected == set()


def test_high_accuracy_can_keep_full_document_docling_for_short_pdf() -> None:
    selected = _selected_docling_pages(
        [],
        page_count=20,
        max_docling_pages=120,
        max_docling_page_ratio=None,
        full_doc_weak_page_ratio=0.25,
        prefer_full_document_docling=True,
    )

    assert selected is None


def test_docling_selection_honors_percentage_cap() -> None:
    weak_pages = [
        WeakPage(page_no=page_no, score=10 - (page_no % 3), flags=["multi_column_layout"])
        for page_no in range(1, 31)
    ]

    selected = _selected_docling_pages(
        weak_pages,
        page_count=100,
        max_docling_pages=40,
        max_docling_page_ratio=0.10,
        full_doc_weak_page_ratio=0.50,
        prefer_full_document_docling=False,
    )

    assert selected is not None
    assert len(selected) == 10


def test_scanned_document_candidate_can_use_full_document_ocr() -> None:
    weak_pages = [
        WeakPage(page_no=page_no, score=8, flags=["image_only_page", "scanned_or_handwritten_candidate"])
        for page_no in range(1, 81)
    ]

    selected = _selected_docling_pages(
        weak_pages,
        page_count=100,
        max_docling_pages=12,
        max_docling_page_ratio=0.10,
        full_doc_weak_page_ratio=0.50,
        prefer_full_document_docling=False,
    )

    assert selected is None
