from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag.ingestion.parsers import document as document_module
from rag.ingestion.parsers.document import parse_document
from rag.ingestion.parsers.images import ImageSource, _pdf_image_source_kind_and_flags

from .pdf_vision_test_support import (
    DummyStore,
    complex_layout_result,
    image_size,
    jpeg_bytes,
)


def test_full_page_low_text_pdf_image_is_layout_repair_candidate() -> None:
    source_kind, flags = _pdf_image_source_kind_and_flags(
        bbox=(0.0, 0.0, 100.0, 100.0),
        page_area=10_000.0,
        page_text_chars=0,
    )

    assert source_kind == "pdf_page_image"
    assert "scanned_or_handwritten_candidate" in flags
    assert "vision_layout_repair_candidate" in flags


def test_complex_layout_page_uses_structured_vision_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = DummyStore()
    analyzer = LayoutAnalyzer(
        blocks=[
            SimpleNamespace(
                block_type="heading",
                text="Case Summary",
                bbox=[0.1, 0.1, 0.8, 0.2],
                confidence=0.9,
            ),
            SimpleNamespace(
                block_type="text",
                text="Left column first. Right column second. Witness statement recovered.",
                confidence=0.86,
            ),
        ],
        confidence=0.88,
    )

    monkeypatch.setattr(
        document_module,
        "_parse_pdf_with_ocr_fallback",
        lambda *args, **kwargs: complex_layout_result(),
    )
    monkeypatch.setattr(
        document_module,
        "pdf_page_image_sources",
        lambda _file_bytes, pages: [_layout_source(page=next(iter(pages)))],
    )
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: [])
    monkeypatch.setattr(
        document_module, "image_dimensions", lambda _content: (100, 100)
    )

    parsed = parse_document(
        b"%PDF-1.7",
        content_type="application/pdf",
        file_path="complex.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=store,
        image_analyzer=analyzer,
        vision_layout_repair_enabled=True,
    )

    assert analyzer.calls == 1
    assert len(store.saved) == 1
    assert parsed.provenance["vision_layout_repair"]["repaired_pages"] == [1]
    assert (
        parsed.provenance["vision_layout_repair"]["evaluations"][0]["reason"]
        == "vision_repaired_reading_order"
    )
    assert parsed.provenance["image_asset_count"] == 1
    assert {item.parser for item in parsed.items} == {"vision_layout"}
    assert parsed.items[0].item_type == "heading"
    assert "vision_layout_repair" in parsed.items[0].quality_flags
    assert "docling_layout_repaired" in parsed.items[0].quality_flags
    assert "layout_repair_source:vision" in parsed.items[0].quality_flags


def test_complex_layout_repair_retries_original_when_resized_result_is_weak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = jpeg_bytes(3000, 1800)
    source = ImageSource(
        content=original,
        content_type="image/jpeg",
        filename="page-1-layout.jpg",
        source_kind="pdf_page_layout",
        quality_flags=["source:pdf_page_image", "vision_layout_repair_candidate"],
        page=1,
        bbox=(0.0, 0.0, 3000.0, 1800.0),
    )
    store = DummyStore()

    class RetryLayoutAnalyzer:
        def __init__(self) -> None:
            self.calls: list[bytes] = []

        def analyze_layout(self, *, content: bytes, content_type: str):
            assert content_type == "image/jpeg"
            self.calls.append(content)
            if len(self.calls) == 1:
                return SimpleNamespace(blocks=[], confidence=0.9, quality_flags=[])
            return SimpleNamespace(
                blocks=[
                    SimpleNamespace(
                        block_type="heading", text="Case Summary", confidence=0.9
                    ),
                    SimpleNamespace(
                        block_type="text",
                        text="Left column first. Right column second. Witness statement recovered.",
                        confidence=0.86,
                    ),
                ],
                confidence=0.88,
                quality_flags=[],
            )

    analyzer = RetryLayoutAnalyzer()
    monkeypatch.setattr(
        document_module,
        "_parse_pdf_with_ocr_fallback",
        lambda *args, **kwargs: complex_layout_result(),
    )
    monkeypatch.setattr(
        document_module, "pdf_page_image_sources", lambda _file_bytes, _pages: [source]
    )
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: [])

    parsed = parse_document(
        b"%PDF-1.7",
        content_type="application/pdf",
        file_path="complex.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=store,
        image_analyzer=analyzer,
        vision_layout_repair_enabled=True,
    )

    assert len(analyzer.calls) == 2
    assert max(image_size(analyzer.calls[0])) == 2048
    assert analyzer.calls[1] == original
    assert store.saved[0][3] == original
    assert parsed.provenance["vision_layout_repair"]["repaired_pages"] == [1]
    assert "vision_layout_retry_original" in parsed.items[0].quality_flags
    assert "vision_layout_retry_original" in parsed.assets[0].quality_flags


def test_complex_layout_keeps_docling_when_vision_is_not_better(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = DummyStore()
    analyzer = LayoutAnalyzer(
        blocks=[SimpleNamespace(block_type="text", text="Too short")], confidence=0.93
    )

    monkeypatch.setattr(
        document_module,
        "_parse_pdf_with_ocr_fallback",
        lambda *args, **kwargs: complex_layout_result(),
    )
    monkeypatch.setattr(
        document_module,
        "pdf_page_image_sources",
        lambda _file_bytes, pages: [_layout_source(page=next(iter(pages)))],
    )
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: [])

    parsed = parse_document(
        b"%PDF-1.7",
        content_type="application/pdf",
        file_path="complex.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=store,
        image_analyzer=analyzer,
        vision_layout_repair_enabled=True,
    )

    assert analyzer.calls == 1
    assert store.saved == []
    assert "vision_layout_repair" not in parsed.provenance
    assert [item.parser for item in parsed.items] == ["docling"]


def test_complex_layout_vision_repair_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = DummyStore()
    analyzer = LayoutAnalyzer(
        blocks=[
            SimpleNamespace(block_type="heading", text="Case Summary", confidence=0.9),
            SimpleNamespace(
                block_type="text",
                text="Recovered reading order with enough content.",
                confidence=0.86,
            ),
        ],
        confidence=0.88,
    )

    monkeypatch.setattr(
        document_module,
        "_parse_pdf_with_ocr_fallback",
        lambda *args, **kwargs: complex_layout_result(),
    )
    monkeypatch.setattr(
        document_module,
        "pdf_page_image_sources",
        lambda _file_bytes, pages: [_layout_source(page=next(iter(pages)))],
    )
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: [])

    parsed = parse_document(
        b"%PDF-1.7",
        content_type="application/pdf",
        file_path="complex.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=store,
        image_analyzer=analyzer,
    )

    assert analyzer.calls == 0
    assert store.saved == []
    assert "vision_layout_repair" not in parsed.provenance
    assert [item.parser for item in parsed.items] == ["docling"]


class LayoutAnalyzer:
    def __init__(self, *, blocks: list[object], confidence: float) -> None:
        self.blocks = blocks
        self.confidence = confidence
        self.calls = 0

    def analyze_layout(self, *, content: bytes, content_type: str):
        self.calls += 1
        return SimpleNamespace(
            blocks=self.blocks, confidence=self.confidence, quality_flags=[]
        )


def _layout_source(*, page: int) -> ImageSource:
    return ImageSource(
        content=b"page-render",
        content_type="image/png",
        filename=f"page-{page}-layout.png",
        source_kind="pdf_page_layout",
        quality_flags=["source:pdf_page_image", "vision_layout_repair_candidate"],
        page=page,
        bbox=(0.0, 0.0, 100.0, 100.0),
    )
