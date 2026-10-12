from rag.ingestion.chunking import chunk_items
from rag.ingestion.chunking.citation_targets import citation_targets
from rag.ingestion.parsers.models import ParsedPdfItem


def item(**updates: object) -> ParsedPdfItem:
    values: dict[str, object] = {
        "index": 0,
        "text": "Cited evidence",
        "item_type": "text",
        "page_start": None,
        "page_end": None,
    }
    values.update(updates)
    return ParsedPdfItem(**values)  # type: ignore[arg-type]


def test_targets_are_format_specific_and_deterministic() -> None:
    assert citation_targets([item(quality_flags=["source:docx_structured"])]) == [
        {
            "kind": "text",
            "exact_text": "Cited evidence",
            "provenance_kind": "native",
            "prefix": "",
            "suffix": "",
        }
    ]
    assert (
        citation_targets([item(page_start=2, page_end=2, bbox=(1, 2, 3, 4))])[0]["kind"]
        == "page"
    )
    assert (
        citation_targets(
            [
                item(
                    page_start=3,
                    page_end=3,
                    bbox=(1, 2, 3, 4),
                    quality_flags=["source:pptx_structured"],
                )
            ]
        )[0]["kind"]
        == "slide"
    )
    assert (
        citation_targets(
            [
                item(
                    page_start=1,
                    page_end=1,
                    bbox=(0, 0, 100, 100),
                    quality_flags=["source:image_file"],
                )
            ]
        )[0]["kind"]
        == "image"
    )


def test_docx_table_target_uses_visible_cell_text() -> None:
    target = citation_targets(
        [
            item(
                text="| <!-- image --> | Search bar |\n| --- | --- |\n| <!-- image --> | Dataset filter |",
                item_type="table",
                quality_flags=["source:docx_structured"],
                table_json={
                    "rows": [
                        ["<!-- image -->", "Search bar"],
                        ["<!-- image -->", "Dataset filter"],
                    ]
                },
            )
        ]
    )[0]

    assert target["exact_text"] == "Search bar Dataset filter"


def test_docx_image_target_uses_asset_without_page_coordinates() -> None:
    target = citation_targets(
        [
            item(
                text="Search bar screenshot",
                item_type="image_text",
                quality_flags=["source:docx_media"],
                image_asset_id="asset-1",
                image_source_kind="docx_media",
                extraction_method="vision_ocr_description",
            )
        ]
    )[0]

    assert target == {
        "kind": "image",
        "bbox": None,
        "exact_text": "Search bar screenshot",
        "confidence": None,
        "image_asset_id": "asset-1",
        "image_source_kind": "docx_media",
        "extraction_method": "vision_ocr_description",
        "provenance_kind": "generated",
    }


def test_docx_context_excludes_appended_image_descriptions() -> None:
    chunks = chunk_items([
        item(text="Policy", item_type="heading", quality_flags=["source:docx_structured"]),
        item(text="Records must be retained.", quality_flags=["source:docx_structured"]),
        item(
            text="Generated screenshot description",
            item_type="image_text",
            image_asset_id="asset-1",
            image_source_kind="docx_media",
        ),
    ], doc_id="doc-1", target_tokens=500, overlap_tokens=0, parent_max_tokens=1000)

    targets = chunks[0].citation_targets
    assert targets[0]["suffix"] == "Records must be retained."
    assert targets[1]["prefix"] == "Policy"
    assert targets[1]["suffix"] == ""
    assert targets[2]["kind"] == "image"


def test_spreadsheet_rows_keep_physical_coordinates() -> None:
    target = citation_targets(
        [
            item(
                item_type="table",
                quality_flags=["source:xlsx", "spreadsheet_table"],
                table_json={
                    "spreadsheet": {
                        "source_name": "Personnel",
                        "data_row_numbers": [4, 8],
                        "header_rows": [2, 3],
                        "column_count": 6,
                    }
                },
            )
        ],
        table_row_index=1,
    )[0]

    assert target == {
        "kind": "spreadsheet",
        "provenance_kind": "structured",
        "sheet_name": "Personnel",
        "start_row": 7,
        "end_row": 8,
        "start_column": 0,
        "end_column": 6,
        "exact_text": "Cited evidence",
    }


def test_json_rows_keep_rfc6901_pointers() -> None:
    target = citation_targets(
        [
            item(
                item_type="table",
                quality_flags=["source:json", "json_array_table"],
                table_json={
                    "json_pointer": "/records",
                    "row_pointers": ["/records/0", "/records/1"],
                },
            )
        ],
        table_row_index=1,
    )[0]

    assert target == {
        "kind": "json",
        "provenance_kind": "structured",
        "pointer": "/records/1",
        "exact_text": "Cited evidence",
    }


def test_ocr_and_generated_description_keep_separate_provenance_after_serialization():
    from rag.ingestion.parsers.models import parsed_item_from_dict, parsed_item_to_dict
    original = item(text="Visible image text:\nRetention is 30 days.\n\nImage description:\nA generated assertion.",
        item_type="image_text", image_source_kind="docx_media", image_asset_id="asset",
        extraction_method="vision_ocr_description", quote_texts=["Retention is 30 days."])
    targets = citation_targets([parsed_item_from_dict(parsed_item_to_dict(original))])
    assert [target["provenance_kind"] for target in targets] == ["generated", "ocr"]
    assert targets[1]["exact_text"] == "Retention is 30 days."
