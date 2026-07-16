from __future__ import annotations

import pytest

from rag.ingestion.errors import UnsupportedPdfError
from rag.ingestion.parsers import document as document_module
from rag.ingestion.parsers.document import parse_document
from rag.ingestion.parsers.models import ParsedImageAsset, ParsedPdfItem

from .pdf_vision_test_support import DummyAnalyzer, DummyStore


def test_pdf_parse_failure_uses_vision_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_parse(*args, **kwargs):
        raise UnsupportedPdfError()

    def fake_image_sources(file_bytes: bytes) -> list[object]:
        assert file_bytes == b"%PDF-1.7"
        return ["page-image"]

    def fake_image_sources_to_items(
        sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None
    ):
        del progress_callback
        assert sources == ["page-image"]
        assert doc_id == "doc-1"
        assert isinstance(store, DummyStore)
        assert isinstance(analyzer, DummyAnalyzer)
        return (
            [
                ParsedPdfItem(
                    index=start_index,
                    text="Visible image text:\nCase No. 123\n\nImage description:\nA scanned case form.",
                    item_type="image_text",
                    page_start=1,
                    page_end=1,
                    parser="pdf_image",
                    quality_flags=[
                        "source:ocr",
                        "source:pdf_page_image",
                        "source:vision",
                        "vision_layout_repair_candidate",
                    ],
                    image_asset_id="asset-1",
                    image_source_kind="pdf_page_image",
                    image_content_type="image/png",
                    extraction_method="vision_ocr_description",
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

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", fail_parse)
    monkeypatch.setattr(document_module, "pdf_image_sources", fake_image_sources)
    monkeypatch.setattr(
        document_module, "image_sources_to_items", fake_image_sources_to_items
    )

    parsed = parse_document(
        b"%PDF-1.7",
        content_type="application/pdf",
        file_path="scan.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
    )

    assert parsed.provenance["primary_parser"] == "vision"
    assert parsed.provenance["secondary_parser"] is None
    assert parsed.provenance["routing_mode"] == "vision_fallback"
    assert parsed.provenance["fallback"] == {
        "from": "layered_docling_ocr",
        "to": "vision",
        "reason": "unsupported_pdf_type",
    }
    assert parsed.provenance["image_asset_count"] == 1
    assert parsed.items[0].text.startswith("Visible image text:")
    assert "vision_pdf_page_fallback" in parsed.items[0].quality_flags
    assert "docling_ocr_empty" in parsed.items[0].quality_flags


def test_pdf_parse_failure_without_vision_context_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_parse(*args, **kwargs):
        raise UnsupportedPdfError()

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", fail_parse)

    with pytest.raises(UnsupportedPdfError):
        parse_document(
            b"%PDF-1.7",
            content_type="application/pdf",
            file_path="scan.pdf",
            min_chars_per_page=10,
        )


def test_pdf_parse_failure_reraises_when_vision_has_no_indexable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_parse(*args, **kwargs):
        raise UnsupportedPdfError()

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", fail_parse)
    monkeypatch.setattr(
        document_module, "pdf_image_sources", lambda _file_bytes: ["page-image"]
    )
    monkeypatch.setattr(
        document_module, "image_sources_to_items", lambda *args, **kwargs: ([], [])
    )

    with pytest.raises(UnsupportedPdfError):
        parse_document(
            b"%PDF-1.7",
            content_type="application/pdf",
            file_path="scan.pdf",
            min_chars_per_page=10,
            doc_id="doc-1",
            image_asset_store=DummyStore(),
            image_analyzer=DummyAnalyzer(),
        )
