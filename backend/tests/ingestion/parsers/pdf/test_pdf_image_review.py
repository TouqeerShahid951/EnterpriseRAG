from __future__ import annotations

import pytest

from rag.ingestion.parsers import document as document_module
from rag.ingestion.parsers.document import (
    PdfImageReviewRequired,
    parse_document,
    resume_pdf_image_review,
)
from rag.ingestion.parsers.images import (
    ImageAnalysisResult,
    ImageSource,
    image_source_candidate_key,
)
from rag.ingestion.parsers.models import (
    ParsedImageAsset,
    ParsedPdfItem,
)

from .pdf_vision_test_support import (
    DummyAnalyzer,
    DummyStore,
    complex_layout_result,
    jpeg_bytes,
    text_result,
)


def test_pdf_auxiliary_image_analysis_is_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [_embedded_source(page=index + 1) for index in range(3)]

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
        assert selected_sources == sources[:2]
        return (
            [
                ParsedPdfItem(
                    index=0,
                    text="Visible image text:\nFigure label",
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
                    source_kind="pdf_image",
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
        lambda *args, **kwargs: complex_layout_result(),
    )
    monkeypatch.setattr(
        document_module, "pdf_image_sources", lambda _file_bytes: sources
    )
    monkeypatch.setattr(
        document_module, "image_sources_to_items", fake_image_sources_to_items
    )

    parsed = parse_document(
        b"%PDF-1.7",
        content_type="application/pdf",
        file_path="figures.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
        pdf_image_analysis_max_images=2,
    )

    assert parsed.provenance["image_analysis_candidate_count"] == 3
    assert parsed.provenance["image_analysis_selected_count"] == 2
    assert parsed.provenance["image_analysis_skipped_count"] == 1
    assert parsed.provenance["image_analysis_skipped_limit_count"] == 1
    assert parsed.provenance["image_asset_count"] == 1


def test_pdf_image_review_threshold_pauses_before_vision_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [_embedded_source(page=index + 1) for index in range(3)]

    def unexpected_image_sources_to_items(*args, **kwargs):
        raise AssertionError("image analysis should not run before image review")

    monkeypatch.setattr(
        document_module,
        "_parse_pdf_with_ocr_fallback",
        lambda *args, **kwargs: complex_layout_result(),
    )
    monkeypatch.setattr(
        document_module, "pdf_image_sources", lambda _file_bytes: sources
    )
    monkeypatch.setattr(
        document_module, "image_sources_to_items", unexpected_image_sources_to_items
    )

    with pytest.raises(PdfImageReviewRequired) as raised:
        parse_document(
            b"%PDF-1.7",
            content_type="application/pdf",
            file_path="figures.pdf",
            min_chars_per_page=10,
            doc_id="doc-1",
            image_asset_store=DummyStore(),
            image_analyzer=DummyAnalyzer(),
            pdf_image_review_threshold=2,
        )

    assert raised.value.parsed.provenance["document_kind"] == "pdf"
    assert raised.value.image_selection.sources == sources
    assert raised.value.visual_sources.image_candidate_count == 3
    assert set(raised.value.image_selection.source_scores) == {
        image_source_candidate_key(source) for source in sources
    }


def test_pdf_image_review_resume_uses_stored_sources_without_pdf_parse() -> None:
    class Analyzer:
        def __init__(self) -> None:
            self.calls = 0

        def analyze_image(
            self, *, content: bytes, content_type: str
        ) -> ImageAnalysisResult:
            self.calls += 1
            assert content_type == "image/jpeg"
            assert content
            return ImageAnalysisResult(
                caption="Approved mission diagram.", confidence=0.88
            )

    source = ImageSource(
        content=jpeg_bytes(64, 64),
        content_type="image/jpeg",
        filename="page-2-image-1.jpg",
        source_kind="pdf_image",
        quality_flags=["source:pdf_image", "image_review_approved"],
        page=2,
        bbox=(10.0, 20.0, 80.0, 90.0),
        page_area_ratio=0.2,
    )
    parsed = resume_pdf_image_review(
        [
            ParsedPdfItem(
                index=0,
                text="Apollo mission body text.",
                item_type="text",
                page_start=2,
                page_end=2,
                parser="pymupdf",
                quality_flags=["source:pymupdf_native"],
            )
        ],
        [source],
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=Analyzer(),
        candidate_count=3,
    )

    assert [item.item_type for item in parsed.items] == ["text", "image_text"]
    assert parsed.provenance["routing_mode"] == "image_review_resume"
    assert parsed.provenance["image_analysis_selected_count"] == 1
    assert parsed.provenance["image_analysis_skipped_review_count"] == 2
    assert parsed.provenance["image_asset_count"] == 1


def test_pdf_auxiliary_image_analysis_skips_duplicate_full_page_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_text = text_result(" ".join(["Recovered text layer."] * 80))
    full_page_scan = ImageSource(
        content=b"full-page-scan",
        content_type="image/png",
        filename="page-1-image-1.png",
        source_kind="pdf_image",
        quality_flags=["source:pdf_image", "full_page_image_candidate"],
        page=1,
        bbox=(0.0, 0.0, 100.0, 100.0),
        page_area_ratio=0.95,
    )
    figure = ImageSource(
        content=b"figure",
        content_type="image/png",
        filename="page-1-image-2.png",
        source_kind="pdf_image",
        quality_flags=["source:pdf_image", "large_image_candidate"],
        page=1,
        bbox=(10.0, 10.0, 55.0, 55.0),
        page_area_ratio=0.12,
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
        assert selected_sources == [figure]
        return (
            [
                ParsedPdfItem(
                    index=0,
                    text="Image description:\nA useful engineering diagram.",
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
                    source_kind="pdf_image",
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
        document_module,
        "pdf_image_sources",
        lambda _file_bytes: [full_page_scan, figure],
    )
    monkeypatch.setattr(
        document_module, "image_sources_to_items", fake_image_sources_to_items
    )

    parsed = parse_document(
        b"%PDF-1.7",
        content_type="application/pdf",
        file_path="ocr-layer.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
        pdf_image_analysis_max_images=48,
    )

    assert parsed.provenance["image_analysis_candidate_count"] == 2
    assert parsed.provenance["image_analysis_selected_count"] == 1
    assert parsed.provenance["image_analysis_skipped_unnecessary_count"] == 1
    assert parsed.provenance["image_asset_count"] == 1


def _embedded_source(*, page: int) -> ImageSource:
    return ImageSource(
        content=f"image-{page}".encode("ascii"),
        content_type="image/png",
        filename=f"page-{page}-image-1.png",
        source_kind="pdf_image",
        quality_flags=["source:pdf_image"],
        page=page,
        bbox=(0.0, 0.0, 100.0, 100.0),
        page_area_ratio=0.12,
    )
