from rag.ingestion.chunking import chunk_items
from rag.ingestion.parsers.hierarchy import apply_hierarchy
from rag.ingestion.parsers.models import ParsedPdfItem


def test_nested_heading_chain_stays_with_following_body() -> None:
    chunks = _chunks(
        apply_hierarchy(
            [
                _item(0, "Employment Terms", "heading", section_level=1),
                _item(1, "Working Time", "heading", section_level=2),
                _item(2, "The employee works forty hours each week."),
                _item(3, "Compensation", "heading", section_level=2),
                _item(4, "The monthly salary is stated in the schedule."),
            ]
        )
    )

    assert len({chunk.parent_chunk_id for chunk in chunks}) == 2
    assert "Employment Terms\n\nWorking Time" in chunks[0].text
    assert "forty hours" in chunks[0].text
    assert chunks[1].text.startswith("Compensation")
    assert all(
        chunk.text not in {"Employment Terms", "Working Time"} for chunk in chunks
    )


def test_table_heading_is_context_not_a_standalone_child() -> None:
    chunks = _chunks(
        apply_hierarchy(
            [
                _item(0, "Format Comparison Table", "heading", section_level=1),
                _item(
                    1,
                    "| Format | Use |\n| --- | --- |\n| PDF | Distribution |",
                    "table",
                    table_json={"rows": [["Format", "Use"], ["PDF", "Distribution"]]},
                ),
            ]
        )
    )

    assert all(chunk.text != "Format Comparison Table" for chunk in chunks)
    assert {chunk.chunk_type for chunk in chunks} == {"table", "table_row"}
    assert all(chunk.table_title == "Format Comparison Table" for chunk in chunks)


def test_spreadsheet_parent_never_crosses_worksheet_boundary() -> None:
    chunks = _chunks(
        [
            _sheet_item(0, "Personnel", "Spreadsheet table: Personnel"),
            _sheet_item(1, "Personnel", "| ID | Name |\n| --- | --- |\n| 1 | Ali |"),
            _sheet_item(2, "Incidents", "Spreadsheet table: Incidents"),
            _sheet_item(3, "Incidents", "| ID | Type |\n| --- | --- |\n| 7 | Safety |"),
        ]
    )

    parents_by_section: dict[str, set[str]] = {}
    for chunk in chunks:
        parents_by_section.setdefault(chunk.section_title or "", set()).add(
            chunk.parent_chunk_id
        )

    assert len(parents_by_section["Personnel"]) == 1
    assert len(parents_by_section["Incidents"]) == 1
    assert parents_by_section["Personnel"].isdisjoint(parents_by_section["Incidents"])


def test_dangling_numbered_marker_moves_to_its_paragraph() -> None:
    chunks = _chunks(
        [
            _item(
                0,
                "The previous provision ends here.\n\n5.",
                section_title="Clause Three",
                section_path=["Clause Three"],
            ),
            _item(
                1,
                "The employee must protect confidential information.",
                section_title="Clause Three",
                section_path=["Clause Three"],
            ),
        ],
        target_tokens=6,
    )

    assert all(not chunk.text.rstrip().endswith("\n5.") for chunk in chunks)
    assert any(chunk.text.startswith("5. The employee") for chunk in chunks)


def test_signature_separator_is_not_embedded() -> None:
    chunks = _chunks(
        [
            _item(
                0,
                "__________________________ f Ali",
                section_title="Signatures",
                section_path=["Signatures"],
            )
        ]
    )

    assert chunks == []


def test_signature_heading_stays_noise_after_names_are_merged_into_it() -> None:
    chunks = _chunks(
        [
            _item(
                0,
                "__________________________ f Ali",
                "heading",
                section_level=1,
            ),
            _item(
                1,
                (
                    "Saif Ali Project Director CYBERARMOUR TECH Private Limited "
                    "The EMPLOYEE Touqeer Shahid Abbasi"
                ),
                section_title="__________________________ f Ali",
                section_path=["__________________________ f Ali"],
            ),
        ]
    )

    assert chunks == []


def test_standalone_page_number_is_not_embedded() -> None:
    chunks = _chunks(
        [
            _item(
                0,
                "19",
                section_title="Objective 4",
                section_path=["Objective 4"],
            )
        ]
    )

    assert chunks == []


def test_numeric_spreadsheet_values_are_preserved() -> None:
    chunks = _chunks([_sheet_item(0, "Metrics", "19")])

    assert len(chunks) == 1
    assert chunks[0].text == "19"


def _chunks(
    items: list[ParsedPdfItem],
    *,
    target_tokens: int = 64,
) -> list:
    return chunk_items(
        items,
        doc_id="document",
        target_tokens=target_tokens,
        overlap_tokens=0,
        parent_max_tokens=256,
    )


def _item(
    index: int,
    text: str,
    item_type: str = "text",
    *,
    section_level: int | None = None,
    section_title: str | None = None,
    section_path: list[str] | None = None,
    table_json: dict[str, object] | None = None,
) -> ParsedPdfItem:
    return ParsedPdfItem(
        index=index,
        text=text,
        item_type=item_type,
        page_start=1,
        page_end=1,
        section_level=section_level,
        section_title=section_title,
        section_path=section_path or [],
        parent_section_id=">".join(section_path or []) or None,
        table_json=table_json,
    )


def _sheet_item(index: int, sheet: str, text: str) -> ParsedPdfItem:
    return ParsedPdfItem(
        index=index,
        text=text,
        item_type="table",
        page_start=None,
        page_end=None,
        section_title=sheet,
        section_path=[sheet],
        parent_section_id=sheet,
        parser="xlsx",
        quality_flags=["source:xlsx", "spreadsheet_table"],
    )
