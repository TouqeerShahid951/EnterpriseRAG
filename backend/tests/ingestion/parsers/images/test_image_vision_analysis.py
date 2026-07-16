from __future__ import annotations

from io import BytesIO

from rag.ingestion.parsers.images import (
    ImageAnalysisResult,
    ImageSource,
    image_sources_to_items,
    parse_image_document,
)

from ..pdf.pdf_vision_test_support import DummyStore, image_size, jpeg_bytes


def test_image_analysis_resizes_temporary_vision_copy_but_stores_original() -> None:
    original = jpeg_bytes(3000, 1000)

    class RecordingAnalyzer:
        def __init__(self) -> None:
            self.calls: list[bytes] = []

        def analyze_image(
            self, *, content: bytes, content_type: str
        ) -> ImageAnalysisResult:
            assert content_type == "image/jpeg"
            self.calls.append(content)
            return ImageAnalysisResult(
                extracted_text="Figure 1",
                caption="A wide engineering figure.",
                confidence=0.9,
            )

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
    assert max(image_size(analyzer.calls[0])) == 2048
    assert "vision_input_resized" in assets[0].quality_flags


def test_image_analysis_retries_original_when_resized_result_is_weak() -> None:
    original = jpeg_bytes(3000, 1800)

    class RetryAnalyzer:
        def __init__(self) -> None:
            self.calls: list[bytes] = []

        def analyze_image(
            self, *, content: bytes, content_type: str
        ) -> ImageAnalysisResult:
            assert content_type == "image/jpeg"
            self.calls.append(content)
            if len(self.calls) == 1:
                return ImageAnalysisResult(quality_flags=["vision_empty_response"])
            return ImageAnalysisResult(
                extracted_text="Recovered OCR text",
                caption="Recovered page description.",
                confidence=0.93,
            )

    store = DummyStore()
    analyzer = RetryAnalyzer()
    items, assets = image_sources_to_items(
        [
            ImageSource(
                content=original,
                content_type="image/jpeg",
                filename="scan.jpg",
                source_kind="pdf_page_image",
                quality_flags=[
                    "source:pdf_page_image",
                    "scanned_or_handwritten_candidate",
                ],
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
    assert max(image_size(analyzer.calls[0])) == 2048
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
        def analyze_image(
            self, *, content: bytes, content_type: str
        ) -> ImageAnalysisResult:
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
