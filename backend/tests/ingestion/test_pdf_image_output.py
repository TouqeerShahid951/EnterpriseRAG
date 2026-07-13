from __future__ import annotations

from rag.ingestion.parsers import document as document_module
from rag.ingestion.parsers.models import ParsedPdfItem

from pdf_vision_test_support import text_items_result


def test_image_text_is_inserted_by_page_bbox() -> None:
    parsed = text_items_result(
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

    result = document_module._append_image_outputs(
        parsed, image_items=[image_item], image_assets=[]
    )

    assert [item.text for item in result.items] == [
        "Before figure.",
        "Image description:\nA diagram between the paragraphs.",
        "After figure.",
    ]
    assert [item.index for item in result.items] == [0, 1, 2]
    assert result.provenance["parser_item_counts"]["vision"] == 1
