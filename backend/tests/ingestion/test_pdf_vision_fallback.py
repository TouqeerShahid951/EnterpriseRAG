from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from rag.ingestion.errors import UnsupportedPdfError
from rag.ingestion.parsers import document as document_module
from rag.ingestion.parsers import images as images_module
from rag.ingestion.parsers.document import PdfImageReviewRequired, _select_pdf_image_sources_for_analysis, parse_document, resume_pdf_image_review
from rag.ingestion.parsers.images import (
    ImageAnalysisResult,
    ImageSource,
    _pdf_image_source_kind_and_flags,
    image_source_candidate_key,
    image_sources_to_items,
    parse_image_document,
)
from rag.ingestion.parsers.models import DocumentParseResult, ParsedImageAsset, ParsedPdfItem


class DummyStore:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, bytes, str]] = []

    def put_image_asset(self, *, doc_id, asset_id, filename, content, content_type):
        self.saved.append((doc_id, asset_id, filename, content, content_type))
        return f"memory://{asset_id}/{filename}"


class DummyAnalyzer:
    pass


def _jpeg_bytes(width: int, height: int) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), color="white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _image_size(content: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        return image.size


def test_image_analysis_resizes_temporary_vision_copy_but_stores_original() -> None:
    original = _jpeg_bytes(3000, 1000)

    class RecordingAnalyzer:
        def __init__(self) -> None:
            self.calls: list[bytes] = []

        def analyze_image(self, *, content: bytes, content_type: str) -> ImageAnalysisResult:
            assert content_type == "image/jpeg"
            self.calls.append(content)
            return ImageAnalysisResult(extracted_text="Figure 1", caption="A wide engineering figure.", confidence=0.9)

    store = DummyStore()
    analyzer = RecordingAnalyzer()
    items, assets = image_sources_to_items(
        [
            ImageSource(
                content=original,
                content_type="image/jpeg",
                filename="figure.jpg",
                source_kind="pdf_image",
                quality_flags=["source:pdf_image"],
                page=1,
            )
        ],
        doc_id="doc-1",
        store=store,
        analyzer=analyzer,
    )

    assert len(items) == 1
    assert len(assets) == 1
    assert store.saved[0][3] == original
    assert assets[0].width == 3000
    assert assets[0].height == 1000
    assert len(analyzer.calls) == 1
    assert max(_image_size(analyzer.calls[0])) == 2048
    assert "vision_input_resized" in assets[0].quality_flags


def test_image_analysis_retries_original_when_resized_result_is_weak() -> None:
    original = _jpeg_bytes(3000, 1800)

    class RetryAnalyzer:
        def __init__(self) -> None:
            self.calls: list[bytes] = []

        def analyze_image(self, *, content: bytes, content_type: str) -> ImageAnalysisResult:
            assert content_type == "image/jpeg"
            self.calls.append(content)
            if len(self.calls) == 1:
                return ImageAnalysisResult(quality_flags=["vision_empty_response"])
            return ImageAnalysisResult(extracted_text="Recovered OCR text", caption="Recovered page description.", confidence=0.93)

    store = DummyStore()
    analyzer = RetryAnalyzer()
    items, assets = image_sources_to_items(
        [
            ImageSource(
                content=original,
                content_type="image/jpeg",
                filename="scan.jpg",
                source_kind="pdf_page_image",
                quality_flags=["source:pdf_page_image", "scanned_or_handwritten_candidate"],
                page=1,
            )
        ],
        doc_id="doc-1",
        store=store,
        analyzer=analyzer,
    )

    assert len(items) == 1
    assert len(assets) == 1
    assert len(analyzer.calls) == 2
    assert max(_image_size(analyzer.calls[0])) == 2048
    assert analyzer.calls[1] == original
    assert "Recovered OCR text" in items[0].text
    assert "vision_retry_original" in assets[0].quality_flags
    assert "vision_empty_response" not in assets[0].quality_flags


def test_standalone_image_with_empty_vision_result_still_indexes_asset() -> None:
    from PIL import Image

    image = Image.new("RGB", (12, 8), color="white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")

    class EmptyAnalyzer:
        def analyze_image(self, *, content: bytes, content_type: str) -> ImageAnalysisResult:
            assert content
            assert content_type == "image/jpeg"
            return ImageAnalysisResult()

    parsed = parse_image_document(
        buffer.getvalue(),
        doc_id="doc-1",
        store=DummyStore(),
        analyzer=EmptyAnalyzer(),
        content_type="image/jpeg",
        filename="blank.jpeg",
    )

    assert len(parsed.assets) == 1
    assert len(parsed.items) == 1
    assert parsed.items[0].image_asset_id == parsed.assets[0].id
    assert "Image file: blank.jpg" in parsed.items[0].text
    assert "vision_empty_result" in parsed.items[0].quality_flags


def test_pdf_parse_failure_uses_vision_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_parse(*args, **kwargs):
        raise UnsupportedPdfError()

    def fake_image_sources(file_bytes: bytes) -> list[object]:
        assert file_bytes == b"%PDF-1.7"
        return ["page-image"]

    def fake_image_sources_to_items(sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None):
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
                    quality_flags=["source:ocr", "source:pdf_page_image", "source:vision", "vision_layout_repair_candidate"],
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
    monkeypatch.setattr(document_module, "image_sources_to_items", fake_image_sources_to_items)

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


def test_pdf_parse_failure_without_vision_context_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_pdf_parse_failure_reraises_when_vision_has_no_indexable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_parse(*args, **kwargs):
        raise UnsupportedPdfError()

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", fail_parse)
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: ["page-image"])
    monkeypatch.setattr(document_module, "image_sources_to_items", lambda *args, **kwargs: ([], []))

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


def test_full_page_low_text_pdf_image_is_layout_repair_candidate() -> None:
    source_kind, flags = _pdf_image_source_kind_and_flags(
        bbox=(0.0, 0.0, 100.0, 100.0),
        page_area=10_000.0,
        page_text_chars=0,
    )

    assert source_kind == "pdf_page_image"
    assert "scanned_or_handwritten_candidate" in flags
    assert "vision_layout_repair_candidate" in flags


def test_complex_layout_page_uses_structured_vision_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    store = DummyStore()
    analyzer = LayoutAnalyzer(
        blocks=[
            SimpleNamespace(block_type="heading", text="Case Summary", bbox=[0.1, 0.1, 0.8, 0.2], confidence=0.9),
            SimpleNamespace(block_type="text", text="Left column first. Right column second. Witness statement recovered.", confidence=0.86),
        ],
        confidence=0.88,
    )

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: _complex_layout_result())
    monkeypatch.setattr(document_module, "pdf_page_image_sources", lambda _file_bytes, pages: [_layout_source(page=next(iter(pages)))])
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: [])
    monkeypatch.setattr(document_module, "image_dimensions", lambda _content: (100, 100))

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
    assert parsed.provenance["vision_layout_repair"]["evaluations"][0]["reason"] == "vision_repaired_reading_order"
    assert parsed.provenance["image_asset_count"] == 1
    assert {item.parser for item in parsed.items} == {"vision_layout"}
    assert parsed.items[0].item_type == "heading"
    assert "vision_layout_repair" in parsed.items[0].quality_flags
    assert "docling_layout_repaired" in parsed.items[0].quality_flags
    assert "layout_repair_source:vision" in parsed.items[0].quality_flags


def test_complex_layout_repair_retries_original_when_resized_result_is_weak(monkeypatch: pytest.MonkeyPatch) -> None:
    original = _jpeg_bytes(3000, 1800)
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
                    SimpleNamespace(block_type="heading", text="Case Summary", confidence=0.9),
                    SimpleNamespace(block_type="text", text="Left column first. Right column second. Witness statement recovered.", confidence=0.86),
                ],
                confidence=0.88,
                quality_flags=[],
            )

    analyzer = RetryLayoutAnalyzer()
    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: _complex_layout_result())
    monkeypatch.setattr(document_module, "pdf_page_image_sources", lambda _file_bytes, _pages: [source])
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
    assert max(_image_size(analyzer.calls[0])) == 2048
    assert analyzer.calls[1] == original
    assert store.saved[0][3] == original
    assert parsed.provenance["vision_layout_repair"]["repaired_pages"] == [1]
    assert "vision_layout_retry_original" in parsed.items[0].quality_flags
    assert "vision_layout_retry_original" in parsed.assets[0].quality_flags


def test_pdf_auxiliary_image_analysis_is_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [_embedded_source(page=index + 1) for index in range(3)]

    def fake_image_sources_to_items(selected_sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None):
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

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: _complex_layout_result())
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: sources)
    monkeypatch.setattr(document_module, "image_sources_to_items", fake_image_sources_to_items)

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


def test_pdf_image_review_threshold_pauses_before_vision_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [_embedded_source(page=index + 1) for index in range(3)]

    def unexpected_image_sources_to_items(*args, **kwargs):
        raise AssertionError("image analysis should not run before image review")

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: _complex_layout_result())
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: sources)
    monkeypatch.setattr(document_module, "image_sources_to_items", unexpected_image_sources_to_items)

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
    assert set(raised.value.image_selection.source_scores) == {image_source_candidate_key(source) for source in sources}


def test_pdf_image_review_resume_uses_stored_sources_without_pdf_parse() -> None:
    class Analyzer:
        def __init__(self) -> None:
            self.calls = 0

        def analyze_image(self, *, content: bytes, content_type: str) -> ImageAnalysisResult:
            self.calls += 1
            assert content_type == "image/jpeg"
            assert content
            return ImageAnalysisResult(caption="Approved mission diagram.", confidence=0.88)

    source = ImageSource(
        content=_jpeg_bytes(64, 64),
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


def test_pdf_auxiliary_image_analysis_skips_duplicate_full_page_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed_text = _text_result(" ".join(["Recovered text layer."] * 80))
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

    def fake_image_sources_to_items(selected_sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None):
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

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: parsed_text)
    monkeypatch.setattr(document_module, "pdf_image_sources", lambda _file_bytes: [full_page_scan, figure])
    monkeypatch.setattr(document_module, "image_sources_to_items", fake_image_sources_to_items)

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


def test_image_selection_prefers_visual_crop_over_full_page_fallbacks() -> None:
    full_page_1 = ImageSource(
        content=b"full-page-1",
        content_type="image/png",
        filename="page-1-image-1.png",
        source_kind="pdf_image",
        quality_flags=["source:pdf_image", "full_page_image_candidate"],
        page=1,
        bbox=(0.0, 0.0, 100.0, 100.0),
        page_area_ratio=1.0,
    )
    full_page_2 = ImageSource(
        content=b"full-page-2",
        content_type="image/png",
        filename="page-2-image-1.png",
        source_kind="pdf_image",
        quality_flags=["source:pdf_image", "full_page_image_candidate"],
        page=2,
        bbox=(0.0, 0.0, 100.0, 100.0),
        page_area_ratio=1.0,
    )
    crop = ImageSource(
        content=b"crop",
        content_type="image/png",
        filename="page-3-visual-region-1.png",
        source_kind="pdf_scanned_visual_region",
        quality_flags=["source:pdf_page_image", "visual_region_crop"],
        page=3,
        bbox=(20.0, 20.0, 60.0, 60.0),
        page_area_ratio=0.16,
    )

    selection = _select_pdf_image_sources_for_analysis(
        [full_page_1, full_page_2, crop],
        [],
        max_images=2,
        max_full_page_fallbacks=8,
        scanned_visual_fallback_pages=frozenset({1, 2}),
    )

    assert selection.sources == [full_page_1, crop]
    assert selection.skipped_limit_count == 1


def test_image_selection_caps_full_page_fallbacks() -> None:
    full_pages = [
        ImageSource(
            content=f"full-page-{page}".encode("ascii"),
            content_type="image/png",
            filename=f"page-{page}-image-1.png",
            source_kind="pdf_image",
            quality_flags=["source:pdf_image", "full_page_image_candidate"],
            page=page,
            bbox=(0.0, 0.0, 100.0, 100.0),
            page_area_ratio=1.0,
        )
        for page in range(1, 4)
    ]
    crop = ImageSource(
        content=b"crop",
        content_type="image/png",
        filename="page-4-visual-region-1.png",
        source_kind="pdf_scanned_visual_region",
        quality_flags=["source:pdf_page_image", "visual_region_crop"],
        page=4,
        bbox=(20.0, 20.0, 60.0, 60.0),
        page_area_ratio=0.16,
    )

    selection = _select_pdf_image_sources_for_analysis(
        [full_pages[0], crop, full_pages[1], full_pages[2]],
        [],
        max_images=10,
        max_full_page_fallbacks=1,
        scanned_visual_fallback_pages=frozenset({1, 2, 3}),
    )

    assert selection.sources == [full_pages[0], crop]
    assert selection.skipped_full_page_fallback_count == 2
    assert selection.skipped_count == 2


def test_image_selection_skips_full_page_when_visual_crop_exists_on_weak_page() -> None:
    full_page = ImageSource(
        content=b"full-page",
        content_type="image/png",
        filename="page-1-image-1.png",
        source_kind="pdf_image",
        quality_flags=["source:pdf_image", "full_page_image_candidate"],
        page=1,
        bbox=(0.0, 0.0, 100.0, 100.0),
        page_area_ratio=1.0,
    )
    crop = ImageSource(
        content=b"crop",
        content_type="image/png",
        filename="page-1-visual-region-1.png",
        source_kind="pdf_scanned_visual_region",
        quality_flags=["source:pdf_page_image", "visual_region_crop"],
        page=1,
        bbox=(20.0, 20.0, 60.0, 60.0),
        page_area_ratio=0.16,
    )

    selection = _select_pdf_image_sources_for_analysis(
        [full_page, crop],
        [],
        max_images=-1,
        scanned_visual_region_pages=frozenset({1}),
        scanned_visual_fallback_pages=frozenset(),
    )

    assert selection.sources == [crop]
    assert selection.skipped_unnecessary_count == 1


def test_scanned_text_only_page_skips_full_page_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_bytes = _scanned_page_pdf(include_visual=False)
    parsed_text = _text_result(" ".join(["Recovered OCR text."] * 90), bbox=_ocr_text_bbox())

    def fake_image_sources_to_items(selected_sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None):
        del doc_id, store, analyzer, start_index, progress_callback
        assert selected_sources == []
        return [], []

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: parsed_text)
    monkeypatch.setattr(document_module, "image_sources_to_items", fake_image_sources_to_items)

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


def test_scanned_mixed_page_crops_visual_region(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_bytes = _scanned_page_pdf(include_visual=True)
    parsed_text = _text_result(" ".join(["Recovered OCR text."] * 90), bbox=_ocr_text_bbox())

    def fake_image_sources_to_items(selected_sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None):
        del doc_id, store, analyzer, start_index, progress_callback
        assert [source.source_kind for source in selected_sources] == ["pdf_scanned_visual_region"]
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

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: parsed_text)
    monkeypatch.setattr(document_module, "image_sources_to_items", fake_image_sources_to_items)

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


def test_scanned_visual_region_prefers_layout_picture_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    Image = pytest.importorskip("PIL.Image")

    page_image = Image.new("RGB", (1000, 1400), "white")
    image_bytes = BytesIO()
    page_image.save(image_bytes, format="PNG")

    class FakePixmap:
        def tobytes(self, _format: str) -> bytes:
            return image_bytes.getvalue()

    class FakePage:
        rect = SimpleNamespace(width=500, height=700)

        def get_pixmap(self, *, dpi: int, alpha: bool):
            assert dpi == 150
            assert alpha is False
            return FakePixmap()

    monkeypatch.setattr(images_module, "prepare_page_layout", lambda _page: [[100, 200, 420, 500, "picture"]])

    regions, tiny_count, ambiguous, cue_count, small_count = images_module._scanned_visual_regions_for_page(
        FakePage(),
        [_ocr_text_bbox()],
        visual_cue_bboxes=[],
        domain_visual_cue=False,
        min_area_ratio=0.03,
        max_regions=-1,
        text_mask_padding_px=8,
    )

    assert len(regions) == 1
    assert regions[0].bbox[0] < 100
    assert regions[0].bbox[1] < 200
    assert regions[0].bbox[2] > 420
    assert regions[0].bbox[3] > 500
    assert "layout_model_region_crop" in regions[0].quality_flags
    assert tiny_count == 0
    assert ambiguous is False
    assert cue_count == 0
    assert small_count == 0


def test_scanned_mixed_page_default_keeps_all_visual_regions(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_bytes = _scanned_page_pdf(include_visual=True, visual_kind="many")
    parsed_text = _text_result(" ".join(["Recovered OCR text."] * 90), bbox=_ocr_text_bbox())

    def fake_image_sources_to_items(selected_sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None):
        del doc_id, store, analyzer, start_index, progress_callback
        assert [source.source_kind for source in selected_sources] == ["pdf_scanned_visual_region"] * 6
        return (
            [
                ParsedPdfItem(
                    index=index,
                    text=f"Image description:\nVisual region {index + 1}.",
                    item_type="image_text",
                    page_start=1,
                    page_end=1,
                    parser="pdf_image",
                    quality_flags=["source:vision", "visual_region_crop"],
                )
                for index in range(6)
            ],
            [
                ParsedImageAsset(
                    id=f"asset-{index + 1}",
                    source_kind="pdf_scanned_visual_region",
                    object_path=f"memory://asset-{index + 1}.png",
                    content_type="image/png",
                    content_hash=f"hash-{index + 1}",
                    page=1,
                    quality_flags=["source:vision", "visual_region_crop"],
                )
                for index in range(6)
            ],
        )

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: parsed_text)
    monkeypatch.setattr(document_module, "image_sources_to_items", fake_image_sources_to_items)

    parsed = parse_document(
        pdf_bytes,
        content_type="application/pdf",
        file_path="scanned-many-visuals.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
    )

    assert parsed.provenance["scanned_page_class_counts"]["scanned_mixed"] == 1
    assert parsed.provenance["scanned_visual_selected_count"] == 6
    assert parsed.provenance["image_analysis_selected_count"] == 6


def test_scanned_page_crops_small_domain_visual_when_text_has_cue(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_bytes = _scanned_page_pdf(include_visual=True, visual_kind="small")
    parsed_text = _text_items_result(
        [
            (" ".join(["Recovered OCR text."] * 90), _ocr_text_bbox()),
            ("Figure 3. Tank recognition marking.", _cue_text_bbox()),
        ]
    )

    def fake_image_sources_to_items(selected_sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None):
        del doc_id, store, analyzer, start_index, progress_callback
        assert len(selected_sources) == 1
        assert selected_sources[0].source_kind == "pdf_scanned_visual_region"
        assert "small_visual_region_crop" in selected_sources[0].quality_flags
        assert "domain_visual_cue_crop" in selected_sources[0].quality_flags
        return (
            [
                ParsedPdfItem(
                    index=0,
                    text="Image description:\nA small tank recognition marking.",
                    item_type="image_text",
                    page_start=1,
                    page_end=1,
                    parser="pdf_image",
                    quality_flags=["source:vision", "small_visual_region_crop"],
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
                    quality_flags=["source:vision", "small_visual_region_crop"],
                )
            ],
        )

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: parsed_text)
    monkeypatch.setattr(document_module, "image_sources_to_items", fake_image_sources_to_items)

    parsed = parse_document(
        pdf_bytes,
        content_type="application/pdf",
        file_path="small-tank-symbol.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
    )

    assert parsed.provenance["scanned_page_class_counts"]["scanned_mixed"] == 1
    assert parsed.provenance["scanned_visual_selected_count"] == 1
    assert parsed.provenance["scanned_visual_small_region_count"] == 1
    assert parsed.provenance["image_analysis_selected_count"] == 1


def test_weak_scanned_page_uses_whole_page_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_bytes = _scanned_page_pdf(include_visual=False)
    parsed_text = _text_result("tiny", bbox=_ocr_text_bbox())

    def fake_image_sources_to_items(selected_sources, *, doc_id, store, analyzer, start_index=0, progress_callback=None):
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

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: parsed_text)
    monkeypatch.setattr(document_module, "image_sources_to_items", fake_image_sources_to_items)

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


def test_complex_layout_keeps_docling_when_vision_is_not_better(monkeypatch: pytest.MonkeyPatch) -> None:
    store = DummyStore()
    analyzer = LayoutAnalyzer(blocks=[SimpleNamespace(block_type="text", text="Too short")], confidence=0.93)

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: _complex_layout_result())
    monkeypatch.setattr(document_module, "pdf_page_image_sources", lambda _file_bytes, pages: [_layout_source(page=next(iter(pages)))])
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


def test_complex_layout_vision_repair_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    store = DummyStore()
    analyzer = LayoutAnalyzer(
        blocks=[
            SimpleNamespace(block_type="heading", text="Case Summary", confidence=0.9),
            SimpleNamespace(block_type="text", text="Recovered reading order with enough content.", confidence=0.86),
        ],
        confidence=0.88,
    )

    monkeypatch.setattr(document_module, "_parse_pdf_with_ocr_fallback", lambda *args, **kwargs: _complex_layout_result())
    monkeypatch.setattr(document_module, "pdf_page_image_sources", lambda _file_bytes, pages: [_layout_source(page=next(iter(pages)))])
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
        return SimpleNamespace(blocks=self.blocks, confidence=self.confidence, quality_flags=[])


def _complex_layout_result() -> DocumentParseResult:
    item = ParsedPdfItem(
        index=0,
        text="Right column second. Left column first. Witness statement.",
        item_type="text",
        page_start=1,
        page_end=1,
        parser="docling",
        quality_flags=["source:docling_layout", "multi_column_layout", "reading_order_ambiguous"],
    )
    return DocumentParseResult(
        items=[item],
        provenance={
            "document_kind": "pdf",
            "primary_parser": "layered",
            "secondary_parser": "docling",
            "routing_mode": "quality_selected_docling",
            "parser_item_counts": {"docling": 1},
            "parser_page_counts": {"docling": 1},
            "quality_flag_counts": {"multi_column_layout": 1, "reading_order_ambiguous": 1},
        },
    )


def _text_result(text: str, *, bbox=None) -> DocumentParseResult:
    item = ParsedPdfItem(
        index=0,
        text=text,
        item_type="text",
        page_start=1,
        page_end=1,
        parser="docling",
        quality_flags=["source:docling"],
        bbox=bbox,
    )
    return DocumentParseResult(
        items=[item],
        provenance={
            "document_kind": "pdf",
            "primary_parser": "layered",
            "secondary_parser": "docling",
            "routing_mode": "quality_selected_docling",
            "parser_item_counts": {"docling": 1},
            "parser_page_counts": {"docling": 1},
            "quality_flag_counts": {"source:docling": 1},
        },
    )


def _text_items_result(entries: list[tuple[str, tuple[float, float, float, float]]]) -> DocumentParseResult:
    items = [
        ParsedPdfItem(
            index=index,
            text=text,
            item_type="text",
            page_start=1,
            page_end=1,
            parser="docling",
            quality_flags=["source:docling"],
            bbox=bbox,
        )
        for index, (text, bbox) in enumerate(entries)
    ]
    return DocumentParseResult(
        items=items,
        provenance={
            "document_kind": "pdf",
            "primary_parser": "layered",
            "secondary_parser": "docling",
            "routing_mode": "quality_selected_docling",
            "parser_item_counts": {"docling": len(items)},
            "parser_page_counts": {"docling": 1},
            "quality_flag_counts": {"source:docling": len(items)},
        },
    )


def test_image_text_is_inserted_by_page_bbox() -> None:
    parsed = _text_items_result(
        [
            ("Before figure.", (72, 80, 520, 120)),
            ("After figure.", (72, 320, 520, 360)),
        ]
    )
    image_item = ParsedPdfItem(
        index=99,
        text="Image description:\nA diagram between the paragraphs.",
        item_type="image_text",
        page_start=1,
        page_end=1,
        parser="vision",
        quality_flags=["source:vision"],
        bbox=(100, 180, 500, 280),
        image_asset_id="asset-1",
        image_source_kind="pdf_scanned_visual_region",
    )

    result = document_module._append_image_outputs(parsed, image_items=[image_item], image_assets=[])

    assert [item.text for item in result.items] == [
        "Before figure.",
        "Image description:\nA diagram between the paragraphs.",
        "After figure.",
    ]
    assert [item.index for item in result.items] == [0, 1, 2]
    assert result.provenance["parser_item_counts"]["vision"] == 1


def _scanned_page_pdf(*, include_visual: bool, visual_kind: str = "large") -> bytes:
    fitz = pytest.importorskip("fitz")
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")

    image = Image.new("RGB", (1000, 1400), "white")
    draw = ImageDraw.Draw(image)
    for y in range(90, 330, 34):
        draw.rectangle((50, y, 520, y + 11), fill=(20, 20, 20))
    if include_visual:
        if visual_kind == "many":
            for left in (570, 770):
                for top in (430, 730, 1030):
                    draw.rectangle((left, top, left + 175, top + 250), fill=(45, 45, 45))
                    draw.rectangle((left + 25, top - 22, left + 105, top + 18), fill=(25, 25, 25))
        elif visual_kind == "small":
            draw.rectangle((700, 520, 805, 610), fill=(45, 45, 45))
            draw.rectangle((730, 495, 780, 525), fill=(25, 25, 25))
            draw.rectangle((775, 505, 850, 518), fill=(25, 25, 25))
            draw.ellipse((705, 590, 805, 635), fill=(20, 20, 20))
        else:
            draw.rectangle((585, 500, 900, 730), fill=(55, 55, 55))
            draw.rectangle((635, 455, 790, 510), fill=(35, 35, 35))
            draw.rectangle((770, 465, 940, 485), fill=(35, 35, 35))
            draw.ellipse((625, 690, 875, 790), fill=(25, 25, 25))
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")
    document = fitz.open()
    page = document.new_page(width=500, height=700)
    page.insert_image(page.rect, stream=image_bytes.getvalue())
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def _ocr_text_bbox():
    return (15.0, 30.0, 280.0, 185.0)


def _cue_text_bbox():
    return (285.0, 320.0, 470.0, 365.0)


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
