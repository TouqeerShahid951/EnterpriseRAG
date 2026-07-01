from __future__ import annotations

from rag_ingestion.config import DEFAULT_TOPIC_TAXONOMY, _topic_taxonomy
from rag_ingestion.chunking import TextChunk
from rag_ingestion.indexing.metadata_text import metadata_prefix, metadata_terms_for_chunk
from rag_ingestion.metadata.topics import classify_topics


def test_topic_taxonomy_has_no_builtin_topics() -> None:
    assert DEFAULT_TOPIC_TAXONOMY == ()
    assert _topic_taxonomy(None) == ()
    assert _topic_taxonomy("") == ()
    assert _topic_taxonomy(" , ") == ()


def test_topic_taxonomy_uses_only_configured_topics() -> None:
    assert _topic_taxonomy("contracts, finance") == ("contracts", "finance")


def test_classifier_uses_configured_taxonomy_without_topic_hints() -> None:
    topics, scores = classify_topics("OCR tools improve text extraction.", ("ocr_tools",))

    assert topics == ["ocr_tools"]
    assert scores == {"ocr_tools": 1.0}


def test_classifier_does_not_treat_it_as_topic_evidence() -> None:
    topics, scores = classify_topics("It extracts text from scanned documents.", ("it_policy",))

    assert topics == []
    assert scores == {}


def test_embedding_metadata_excludes_topics() -> None:
    chunk = TextChunk(
        index=0,
        page=1,
        text="The body discusses scanned forms.",
        parent_chunk_id="doc:parent:0",
        parent_text="The body discusses scanned forms.",
        chunk_type="text",
        section_title="Findings",
        page_start=1,
        page_end=1,
    )
    metadata = {
        "summary": "A document about forms.",
        "topics": ["OCR"],
        "llm_topics": ["Handwriting recognition"],
    }

    prefix = metadata_prefix(title="Report.pdf", chunk=chunk, metadata=metadata)
    terms = metadata_terms_for_chunk(title="Report.pdf", chunk=chunk, metadata=metadata)

    assert "Topics:" not in prefix
    assert "OCR" not in terms
    assert "Handwriting" not in terms
