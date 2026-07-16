from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from rag.ingestion.parsers import document as document_module
from rag.ingestion.parsers import images as images_module
from rag.ingestion.parsers.document import parse_document
from rag.ingestion.parsers.models import (
    ParsedImageAsset,
    ParsedPdfItem,
)

from .pdf_scanned_test_support import cue_text_bbox, ocr_text_bbox, scanned_page_pdf
from .pdf_vision_test_support import (
    DummyAnalyzer,
    DummyStore,
    text_items_result,
    text_result,
)


def test_scanned_visual_region_prefers_layout_picture_bbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(
        images_module,
        "prepare_page_layout",
        lambda _page: [[100, 200, 420, 500, "picture"]],
    )

    regions, tiny_count, ambiguous, cue_count, small_count = (
        images_module._scanned_visual_regions_for_page(
            FakePage(),
            [ocr_text_bbox()],
            visual_cue_bboxes=[],
            domain_visual_cue=False,
            min_area_ratio=0.03,
            max_regions=-1,
            text_mask_padding_px=8,
        )
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


def test_scanned_mixed_page_default_keeps_all_visual_regions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = scanned_page_pdf(include_visual=True, visual_kind="many")
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
        ] * 6
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
        file_path="scanned-many-visuals.pdf",
        min_chars_per_page=10,
        doc_id="doc-1",
        image_asset_store=DummyStore(),
        image_analyzer=DummyAnalyzer(),
    )

    assert parsed.provenance["scanned_page_class_counts"]["scanned_mixed"] == 1
    assert parsed.provenance["scanned_visual_selected_count"] == 6
    assert parsed.provenance["image_analysis_selected_count"] == 6


def test_scanned_page_crops_small_domain_visual_when_text_has_cue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = scanned_page_pdf(include_visual=True, visual_kind="small")
    parsed_text = text_items_result(
        [
            (" ".join(["Recovered OCR text."] * 90), ocr_text_bbox()),
            ("Figure 3. Tank recognition marking.", cue_text_bbox()),
        ]
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
