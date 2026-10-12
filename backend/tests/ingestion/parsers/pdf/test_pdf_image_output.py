from __future__ import annotations

from dataclasses import replace

import pytest

from rag.ingestion.chunking import chunk_items
from rag.ingestion.chunking.citation_targets import citation_targets
from rag.ingestion.parsers import document as document_module
from rag.ingestion.parsers.images.analysis import image_item_description, image_item_text
from rag.ingestion.parsers.models import DocumentParseResult, ParsedPdfItem, parsed_item_from_dict, parsed_item_to_dict
from rag.ingestion.parsers.pdf.ocr_reconciliation import consolidate_image_ocr
from rag.ingestion.pipeline.steps import _low_confidence_ocr_items
from rag.ingestion.review.corrections import apply_review_correction

from .pdf_vision_test_support import text_items_result


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


def _ocr_block(**updates) -> ParsedPdfItem:
    return replace(ParsedPdfItem(
        index=0, text="Retention is 30 days.", item_type="text",
        page_start=1, page_end=1, bbox=(10, 10, 100, 30),
        parser="docling", quality_flags=["source:ocr", "docling_ocr"], confidence=0.6,
    ), **updates)


def _image_ocr(**updates) -> ParsedPdfItem:
    transcription = "Retention is 30 days.\nArchive records.\nUnique image text."
    return replace(ParsedPdfItem(
        index=10, text=image_item_text(transcription, "An administrative form."),
        quote_texts=[transcription], item_type="image_text", page_start=1, page_end=1,
        bbox=(0, 0, 500, 500), image_asset_id="asset-1", image_source_kind="pdf_image",
        parser="pdf_image", quality_flags=["source:ocr", "source:vision"], confidence=0.99,
        extraction_method="vision_ocr_description",
    ), **updates)


def _merged(blocks, image=None):
    return document_module._append_image_outputs(
        DocumentParseResult(items=blocks, provenance={}),
        image_items=[image or _image_ocr()], image_assets=[],
    )


@pytest.mark.parametrize("confidence", [None, 0.6])
def test_duplicate_ocr_has_one_review_and_one_indexed_transcription(confidence) -> None:
    result = _merged([
        _ocr_block(confidence=confidence),
        _ocr_block(index=1, text="Archive\nrecords.", bbox=(10, 40, 100, 60)),
    ])
    assert len(result.items) == 1
    image = result.items[0]
    assert image.index == 0
    assert image.confidence == confidence
    assert image.image_asset_id == "asset-1"
    assert len(image.source_spans) == 2
    assert "ocr_image_consolidated" in image.quality_flags
    review = _low_confidence_ocr_items(result.items, 0.9)
    assert len(review) == 1
    assert review[0]["partial_text"] == image.quote_texts[0]
    assert "An administrative form." not in review[0]["partial_text"]
    assert result.provenance["parser_item_counts"] == {"pdf_image": 1}
    chunks = chunk_items(result.items, doc_id="doc", target_tokens=500, overlap_tokens=0, parent_max_tokens=1000)
    assert sum(chunk.text.count("Retention is 30 days.") for chunk in chunks) == 1
    assert any("Unique image text." in chunk.text for chunk in chunks)
    targets = citation_targets([parsed_item_from_dict(parsed_item_to_dict(image))])
    assert any(target["bbox"] == [10, 10, 100, 30] and target["provenance_kind"] == "ocr" for target in targets)
    assert any(target["provenance_kind"] == "generated" for target in targets)
    assert consolidate_image_ocr([], result.items) == ([], result.items)


@pytest.mark.parametrize("updates", [
    {"text": "Retention is 90 days."},
    {"text": "An administrative form."},
    {"text": "Unique OCR-only information."},
    {"text": "days"},
    {"page_start": 2, "page_end": 2},
    {"page_end": 2},
    {"bbox": (600, 10, 700, 30)},
    {"bbox": (490, 10, 550, 30)},
    {"bbox": None},
    {"bbox": (0, 0, float("nan"), 10)},
    {"quality_flags": ["source:pymupdf_native"]},
    {"item_type": "heading"},
    {"item_type": "table", "table_json": {"rows": [["Retention is 30 days."]]}},
    {"source_spans": [{"page": 2, "bbox": [10, 10, 100, 30], "exact_text": "Retention is 30 days."}]},
])
def test_nonduplicate_or_uncertain_ocr_is_preserved(updates) -> None:
    block = _ocr_block(**updates)
    result = _merged([block])
    assert len(result.items) == 2
    assert any(replace(item, index=block.index) == block for item in result.items)
    assert all("ocr_image_consolidated" not in item.quality_flags for item in result.items)


def test_repeated_text_occurrences_are_not_collapsed_by_text_alone() -> None:
    result = _merged([
        _ocr_block(),
        _ocr_block(index=1, bbox=(10, 40, 100, 60)),
    ])
    assert len(result.items) == 2
    assert sum(item.item_type == "text" for item in result.items) == 1
    assert len(next(item for item in result.items if item.item_type == "image_text").source_spans) == 1


@pytest.mark.parametrize("updates", [
    {"image_source_kind": "docx_media", "page_start": None, "page_end": None, "bbox": None},
    {"quote_texts": None},
    {"quote_texts": []},
    {"extraction_method": None},
    {"image_asset_id": None},
])
def test_images_without_pdf_transcription_provenance_do_not_absorb_text(updates) -> None:
    assert len(_merged([_ocr_block()], _image_ocr(**updates)).items) == 2


def test_description_label_inside_visible_text_is_not_a_separator() -> None:
    transcription = "Retention is 30 days.\n\nImage description:\nPrinted field label."
    image = _image_ocr(text=image_item_text(transcription, "Generated context."), quote_texts=[transcription])
    assert image_item_description(image) == "Generated context."
    result = _merged([_ocr_block()], image)
    corrected = apply_review_correction(parsed_item_to_dict(result.items[0]), transcription)
    assert corrected["quote_texts"] == [transcription]
    assert corrected["text"] == image.text


def test_approval_preserves_description_and_only_quotes_corrected_transcription() -> None:
    original = parsed_item_to_dict(_merged([_ocr_block()]).items[0])
    corrected_text = "Retention is 90 days.\nArchive records.\nUnique image text."
    corrected = apply_review_correction(original, corrected_text)
    assert original["quote_texts"] == _image_ocr().quote_texts
    assert corrected["quote_texts"] == [corrected_text]
    assert corrected["text"] == image_item_text(corrected_text, "An administrative form.")
    assert apply_review_correction(corrected, corrected_text) == corrected
    assert corrected["source_spans"] == original["source_spans"]
    targets = citation_targets([parsed_item_from_dict(corrected)])
    quotes = [target["exact_text"] for target in targets if target["provenance_kind"] == "ocr"]
    assert quotes == [corrected_text]
    assert not any("30 days" in quote or "administrative form" in quote for quote in quotes)


def test_legacy_review_payload_keeps_its_original_shape() -> None:
    original = {"index": 0, "text": "Legacy OCR", "quality_flags": None}
    assert apply_review_correction(original, "Corrected") == {
        "index": 0, "text": "Corrected", "quality_flags": ["ocr_review_approved"],
    }
