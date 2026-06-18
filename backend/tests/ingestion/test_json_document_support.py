from __future__ import annotations

import pytest
from fastapi import HTTPException

from rag.query.qdrant import SearchHit
from rag.query.query_retrieval import _promote_structured_matches
from rag.services.document_uploads import JSON_CONTENT_TYPE, validated_document_type
from rag_ingestion.chunking import chunk_items
from rag_ingestion.errors import WorkerStepError
from rag_ingestion.parsers.document import parse_document
from rag_ingestion.parsers.json import parse_json_document


def test_valid_json_upload_is_accepted_by_filename_and_content_type() -> None:
    content = b'{"case_id":"FIR-001","accused":"Sajjad Hussain"}'

    assert validated_document_type(content, "records.json", "application/octet-stream") == JSON_CONTENT_TYPE
    assert validated_document_type(content, "records.bin", "application/json") == JSON_CONTENT_TYPE


def test_invalid_json_upload_is_rejected_cleanly() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validated_document_type(b'{"case_id":', "records.json", "application/json")

    assert exc_info.value.detail["code"] == "invalid_json"


def test_json_parser_emits_stable_paths_for_nested_values() -> None:
    parsed = parse_document(
        b'{"bundle":{"content":{"sections":[{"title":"Summary","blocks":[{"kind":"paragraph","text":"Finding A"}]}]}}}',
        content_type="application/json",
        file_path="memory://bundle.json",
        min_chars_per_page=10,
    )

    text = "\n\n".join(item.text for item in parsed.items)
    assert parsed.provenance["document_kind"] == "json"
    assert parsed.provenance["primary_parser"] == "json"
    assert "JSON path: bundle.content.sections[0]" in text
    assert "title: Summary" in text
    assert "JSON path for title: bundle.content.sections[0].title" in text
    assert "JSON path for text: bundle.content.sections[0].blocks[0].text" in text


def test_json_parser_dispatches_from_bytes_when_metadata_is_missing() -> None:
    parsed = parse_document(
        b'{"case_id":"FIR-001","accused_name":"Sajjad Hussain"}',
        content_type=None,
        file_path="memory://48654c37",
        min_chars_per_page=10,
    )

    text = "\n\n".join(item.text for item in parsed.items)
    assert parsed.provenance["document_kind"] == "json"
    assert parsed.provenance["primary_parser"] == "json"
    assert "JSON path for case id: case_id" in text


def test_json_parser_reports_json_specific_parse_failures() -> None:
    with pytest.raises(WorkerStepError) as exc_info:
        parse_json_document(b'{"case_id":')

    assert exc_info.value.code == "json_parse_failed"


def test_json_table_like_shapes_emit_structured_table_rows() -> None:
    parsed = parse_json_document(
        b"""
        {
          "table": {
            "headers": ["Accused Name", "Case Reference"],
            "rows": [
              {"values": ["Sajjad Hussain", "FIR 01"]},
              {"values": ["Imran Zafar", "FIR 03"]}
            ]
          }
        }
        """
    )

    chunks = chunk_items(parsed.items, doc_id="doc-json", target_tokens=128, overlap_tokens=0, parent_max_tokens=512)
    row_chunks = [chunk for chunk in chunks if chunk.chunk_type == "table_row"]

    assert row_chunks
    assert row_chunks[0].structured_kind == "table_row"
    assert {"label": "Accused Name", "value": "Sajjad Hussain"} in row_chunks[0].structured_fields
    assert any(field["label"] == "JSON path" and field["value"] == "table.rows[0]" for field in row_chunks[0].structured_fields)


def test_json_object_chunks_promote_underscore_keys_as_kv_records() -> None:
    parsed = parse_json_document(b'{"case_id":"FIR-001","accused_name":"Sajjad Hussain"}')

    chunks = chunk_items(parsed.items, doc_id="doc-json", target_tokens=128, overlap_tokens=0, parent_max_tokens=512)
    record_chunks = [chunk for chunk in chunks if chunk.structured_kind == "kv_record"]

    assert record_chunks
    assert "case id" in record_chunks[0].structured_field_names
    assert {"label": "case id", "value": "FIR-001"} in record_chunks[0].structured_fields
    assert {"label": "JSON path for case id", "value": "case_id"} in record_chunks[0].structured_fields


def test_structured_json_field_matches_are_promoted_for_queries() -> None:
    hits = [
        _hit("other", text="General case narrative."),
        _hit(
            "json",
            text="case_id: FIR-001\naccused: Sajjad Hussain",
            structured_kind="kv_record",
            structured_field_names=["case id", "accused"],
            structured_fields=[{"label": "case_id", "value": "FIR-001"}, {"label": "accused", "value": "Sajjad Hussain"}],
        ),
    ]

    promoted = _promote_structured_matches(hits, "What is the case id?")

    assert promoted[0].payload["chunk_id"] == "json"


def _hit(point_id: str, *, text: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=0.2,
        payload={
            "doc_id": "doc-json",
            "chunk_id": point_id,
            "doc_title": "records.json",
            "text": text,
            **payload,
        },
    )
