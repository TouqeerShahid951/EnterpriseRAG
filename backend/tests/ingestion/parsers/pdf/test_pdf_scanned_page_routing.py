from __future__ import annotations

import pytest

from rag.ingestion.parsers import document as document_module
from rag.ingestion.parsers.document import parse_document
from rag.ingestion.parsers.models import ParsedImageAsset, ParsedPdfItem

from .pdf_scanned_test_support import ocr_text_bbox, scanned_page_pdf
from .pdf_vision_test_support import DummyAnalyzer, DummyStore, text_result


def test_scanned_text_only_page_skips_full_page_vision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = scanned_page_pdf(include_visual=False)
    parsed_text = text_result(
        " ".join(["Recovered OCR text."] * 90), bbox=ocr_text_bbox()
    )

    def fake_image_sources_to_items(
        selected_sources,
        *,
        doc_id,
        store,
        analyzer,
        start_index=0,
        progress_callback=None,
    ):
        del doc_id, store, analyzer, start_index, progress_callback
        assert selected_sources == []
        return [], []

    monkeypatch.setattr(
        document_module,
        "_parse_pdf_with_ocr_fallback",
        lambda *args, **kwargs: parsed_text,
    )
    monkeypatch.setattr(
        document_module, "image_sources_to_items", fake_image_sources_to_items
    )

    parsed = parse_document(
        pdf_bytes,
        content_type="application/pdf",
        file_path="scanned-text.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
    )

    assert parsed.provenance["scanned_page_class_counts"]["scanned_text_only"] == 1
    assert parsed.provenance["scanned_visual_selected_count"] == 0
    assert parsed.provenance["scanned_visual_skipped_text_only_count"] == 1
    assert parsed.provenance["image_analysis_selected_count"] == 0
    assert parsed.provenance["image_analysis_skipped_unnecessary_count"] == 1


def test_scanned_mixed_page_crops_visual_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = scanned_page_pdf(include_visual=True)
    parsed_text = text_result(
        " ".join(["Recovered OCR text."] * 90), bbox=ocr_text_bbox()
    )

    def fake_image_sources_to_items(
        selected_sources,
        *,
        doc_id,
        store,
        analyzer,
        start_index=0,
        progress_callback=None,
    ):
        del doc_id, store, analyzer, start_index, progress_callback
        assert [source.source_kind for source in selected_sources] == [
            "pdf_scanned_visual_region"
        ]
        assert "visual_region_crop" in selected_sources[0].quality_flags
        return (
            [
                ParsedPdfItem(
                    index=0,
                    text="Image description:\nA tracked armored vehicle silhouette.",
                    item_type="image_text",
                    page_start=1,
                    page_end=1,
                    parser="pdf_image",
                    quality_flags=["source:vision", "visual_region_crop"],
                )
            ],
            [
                ParsedImageAsset(
                    id="asset-1",
                    source_kind="pdf_scanned_visual_region",
                    object_path="memory://asset-1.png",
                    content_type="image/png",
                    content_hash="hash",
                    page=1,
                    quality_flags=["source:vision", "visual_region_crop"],
                )
            ],
        )

    monkeypatch.setattr(
        document_module,
        "_parse_pdf_with_ocr_fallback",
        lambda *args, **kwargs: parsed_text,
    )
    monkeypatch.setattr(
        document_module, "image_sources_to_items", fake_image_sources_to_items
    )

    parsed = parse_document(
        pdf_bytes,
        content_type="application/pdf",
        file_path="scanned-mixed.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
    )

    assert parsed.provenance["scanned_page_class_counts"]["scanned_mixed"] == 1
    assert parsed.provenance["scanned_visual_selected_count"] == 1
    assert parsed.provenance["image_analysis_selected_count"] == 1
    assert parsed.provenance["image_asset_count"] == 1


def test_weak_scanned_page_uses_whole_page_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = scanned_page_pdf(include_visual=False)
    parsed_text = text_result("tiny", bbox=ocr_text_bbox())

    def fake_image_sources_to_items(
        selected_sources,
        *,
        doc_id,
        store,
        analyzer,
        start_index=0,
        progress_callback=None,
    ):
        del doc_id, store, analyzer, start_index, progress_callback
        assert len(selected_sources) == 1
        assert selected_sources[0].source_kind == "pdf_page_image"
        return (
            [
                ParsedPdfItem(
                    index=0,
                    text="Visible image text:\nRecovered weak scan text.",
                    item_type="image_text",
                    page_start=1,
                    page_end=1,
                    parser="pdf_image",
                    quality_flags=["source:vision"],
                )
            ],
            [
                ParsedImageAsset(
                    id="asset-1",
                    source_kind="pdf_page_image",
                    object_path="memory://asset-1.png",
                    content_type="image/png",
                    content_hash="hash",
                    page=1,
                    quality_flags=["source:vision"],
                )
            ],
        )

    monkeypatch.setattr(
        document_module,
        "_parse_pdf_with_ocr_fallback",
        lambda *args, **kwargs: parsed_text,
    )
    monkeypatch.setattr(
        document_module, "image_sources_to_items", fake_image_sources_to_items
    )

    parsed = parse_document(
        pdf_bytes,
        content_type="application/pdf",
        file_path="weak-scan.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
    )

    assert parsed.provenance["scanned_page_class_counts"]["scanned_image_only"] == 1
    assert parsed.provenance["scanned_visual_whole_page_fallback_count"] == 1
    assert parsed.provenance["image_analysis_selected_count"] == 1
