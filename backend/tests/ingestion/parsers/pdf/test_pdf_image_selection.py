from __future__ import annotations

from rag.ingestion.parsers.document import _select_pdf_image_sources_for_analysis
from rag.ingestion.parsers.images import ImageSource


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
