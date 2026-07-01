from __future__ import annotations

from rag.query.metadata_scoring import low_value_chunk_penalty, metadata_boost_hits
from rag.query.qdrant import SearchHit


def test_topic_only_overlap_gets_small_topic_boost_without_metadata_boost() -> None:
    hit = SearchHit(
        point_id="doc:1",
        score=0.2,
        payload={
            "doc_id": "doc",
            "chunk_id": "doc:1",
            "text": "The body discusses unrelated maintenance steps.",
            "topics": ["ocr"],
            "metadata_terms": ["ocr"],
        },
    )

    boosted = metadata_boost_hits("ocr", [hit])[0]

    assert boosted.score == hit.score
    assert "_metadata_score" not in boosted.payload
    assert "_metadata_boosted_score" not in boosted.payload
    assert boosted.payload["_topic_score"] == 1.0
    assert boosted.payload["_topic_matches"] == ["ocr"]
    assert boosted.payload["_topic_boost"] == 0.05
    assert boosted.payload["_topic_boosted_score"] == 0.25


def test_curated_topic_match_outranks_generated_topic_match_when_scores_are_similar() -> None:
    curated = SearchHit(
        point_id="curated",
        score=0.2,
        payload={"doc_id": "curated", "chunk_id": "curated", "topics": ["OCR"]},
    )
    generated = SearchHit(
        point_id="generated",
        score=0.2,
        payload={"doc_id": "generated", "chunk_id": "generated", "llm_topics": ["OCR"]},
    )

    ranked = metadata_boost_hits("ocr", [generated, curated])

    assert [hit.point_id for hit in ranked] == ["curated", "generated"]
    assert ranked[0].payload["_topic_score"] == 1.0
    assert ranked[1].payload["_topic_score"] == 0.5


def test_topic_boost_does_not_overpower_larger_base_score_gap() -> None:
    high_base = SearchHit(
        point_id="high",
        score=0.22,
        payload={"doc_id": "high", "chunk_id": "high"},
    )
    low_base_topic = SearchHit(
        point_id="low-topic",
        score=0.16,
        payload={"doc_id": "low-topic", "chunk_id": "low-topic", "topics": ["OCR"]},
    )

    ranked = metadata_boost_hits("ocr", [low_base_topic, high_base])

    assert [hit.point_id for hit in ranked] == ["high", "low-topic"]


def test_low_value_penalty_detects_page_number_only_chunks() -> None:
    page_number = SearchHit(
        point_id="page",
        score=0.2,
        payload={"doc_id": "doc", "chunk_id": "page", "text": "Page 4 of 10"},
    )

    penalty, reasons = low_value_chunk_penalty("what is the warranty period", page_number)

    assert penalty > 0
    assert "page_number_only" in reasons


def test_low_value_penalty_respects_explicit_page_number_queries() -> None:
    page_number = SearchHit(
        point_id="page",
        score=0.2,
        payload={"doc_id": "doc", "chunk_id": "page", "text": "Page 4 of 10"},
    )

    penalty, reasons = low_value_chunk_penalty("what page number contains warranty details", page_number)

    assert penalty == 0
    assert reasons == []


def test_low_value_penalty_applies_small_footnote_penalty_unless_requested() -> None:
    footnote = SearchHit(
        point_id="note",
        score=0.2,
        payload={"doc_id": "doc", "chunk_id": "note", "text": "[1] Internal archive reference."},
    )

    penalty, reasons = low_value_chunk_penalty("what is the archive reference", footnote)
    requested_penalty, requested_reasons = low_value_chunk_penalty("show the footnotes about archive references", footnote)

    assert penalty == 0.08
    assert reasons == ["footnote"]
    assert requested_penalty == 0
    assert requested_reasons == []


def test_low_value_penalty_does_not_treat_short_structured_rows_as_low_information() -> None:
    row = SearchHit(
        point_id="row",
        score=0.2,
        payload={
            "doc_id": "doc",
            "chunk_id": "row",
            "text": "500",
            "chunk_type": "table_row",
            "structured_fields": [{"label": "Maximum Limit", "value": "500"}],
        },
    )

    penalty, reasons = low_value_chunk_penalty("what is the maximum limit", row)

    assert penalty == 0
    assert reasons == []
