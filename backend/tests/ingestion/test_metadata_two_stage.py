from __future__ import annotations

from types import SimpleNamespace

from rag.ingestion.metadata.two_stage import generate_metadata_v2


def test_single_window_metadata_skips_consolidation_call() -> None:
    calls: list[str] = []

    def generate_metadata(prompt: str) -> dict[str, object]:
        calls.append(prompt)
        return {"summary": "One image table.", "llm_topics": ["tables"], "doc_type": "image", "claims": []}

    result = generate_metadata_v2([SimpleNamespace(text="handwritten table")], generate_metadata)

    assert len(calls) == 1
    assert result["_metadata_extraction"]["mode"] == "llm_single_window"
    assert result["summary"] == "One image table."


def test_multi_window_metadata_still_consolidates() -> None:
    calls: list[str] = []

    def generate_metadata(prompt: str) -> dict[str, object]:
        calls.append(prompt)
        if prompt.startswith("Merge metadata"):
            return {"summary": "Consolidated summary.", "llm_topics": ["policy"], "doc_type": "report", "claims": []}
        return {"summary": "Window summary.", "llm_topics": ["window"], "doc_type": "section", "claims": []}

    result = generate_metadata_v2(
        [SimpleNamespace(text="alpha window text"), SimpleNamespace(text="beta window text")],
        generate_metadata,
        max_window_chars=12,
    )

    assert len(calls) == 3
    assert calls[-1].startswith("Merge metadata")
    assert "claims" not in calls[-1]
    assert result["_metadata_extraction"]["mode"] == "llm_consolidated"
    assert result["summary"] == "Consolidated summary."
