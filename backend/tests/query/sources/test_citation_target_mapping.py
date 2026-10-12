import pytest

from rag.query.sources.source_mapping import citation_targets_from_payload


def test_indexed_citation_targets_are_validated_at_the_query_boundary() -> None:
    targets = citation_targets_from_payload({
        "citation_targets": [
            {
                "kind": "spreadsheet",
                "sheet_name": "Personnel",
                "start_row": 6,
                "end_row": 7,
                "start_column": 0,
                "end_column": 8,
            }
        ]
    })

    assert targets[0].kind == "spreadsheet"


def test_invalid_indexed_citation_target_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="indexed citation targets are invalid"):
        citation_targets_from_payload({
            "citation_targets": [{"kind": "spreadsheet", "sheet_name": "Personnel"}]
        })
