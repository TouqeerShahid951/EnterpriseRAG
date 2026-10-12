import json

from rag.ingestion.metadata.spreadsheet_schema import (
    SPREADSHEET_SCHEMA_WARNING,
    enrich_spreadsheet_schema_items,
)
from rag.ingestion.parsers.models import ParsedPdfItem


def test_schema_enrichment_adds_grounded_aliases_only_to_schema_item() -> None:
    schema = _item("spreadsheet_schema", rows=[["AC_ID", "LOC_CD"]])
    data = _item("spreadsheet_table", rows=[["AC_ID", "LOC_CD"], ["A-101", "ISB-01"]])

    enriched, warnings = enrich_spreadsheet_schema_items(
        [schema, data],
        lambda **_kwargs: json.dumps(
            {
                "tables": [
                    {
                        "name": "Aircraft",
                        "description": "Aircraft location records.",
                        "columns": [
                            {
                                "name": "LOC_CD",
                                "description": "Current location code.",
                                "aliases": ["location", "station"],
                                "uncertain": False,
                            },
                            {
                                "name": "INVENTED",
                                "description": "Must be discarded.",
                                "aliases": [],
                                "uncertain": False,
                            },
                        ],
                    }
                ]
            }
        ),
    )

    assert warnings == []
    assert "Aircraft location records" in enriched[0].text
    assert "aliases: location, station" in enriched[0].text
    assert "INVENTED" not in enriched[0].text
    assert enriched[1] == data


def test_schema_enrichment_failure_keeps_deterministic_schema() -> None:
    schema = _item("spreadsheet_schema", rows=[["AC_ID"]])

    def fail(**_kwargs):
        raise RuntimeError("offline")

    enriched, warnings = enrich_spreadsheet_schema_items([schema], fail)

    assert enriched == [schema]
    assert warnings == [SPREADSHEET_SCHEMA_WARNING]


def _item(flag: str, *, rows: list[list[str]]) -> ParsedPdfItem:
    return ParsedPdfItem(
        index=0,
        text="Spreadsheet table: Aircraft\nColumns:\n- AC_ID (text)\n- LOC_CD (text)",
        item_type="table",
        page_start=None,
        page_end=None,
        section_title="Aircraft",
        quality_flags=["source:xlsx", flag],
        table_json={"caption": "Aircraft", "rows": rows},
    )
