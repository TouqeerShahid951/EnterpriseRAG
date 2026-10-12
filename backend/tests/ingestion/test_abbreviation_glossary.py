import logging
from types import SimpleNamespace
from typing import Any

import pytest

from rag.shared.contracts.abbreviations import (
    ABBREVIATION_GLOSSARY_DOC_TYPE,
    abbreviation_entries,
)
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.adapters import backend as backend_adapter
from rag.ingestion.adapters.backend import BackendInternalClient
from rag.ingestion.pipeline import indexing_stages


def test_abbreviation_entries_support_tables_and_delimited_lines() -> None:
    assert abbreviation_entries(
        "",
        [
            {"label": "Acronym", "value": "AD"},
            {"label": "Full form", "value": "Assistant Director"},
        ],
    ) == [("AD", "Assistant Director")]
    assert abbreviation_entries("FIA — Federal Investigation Agency") == [
        ("FIA", "Federal Investigation Agency")
    ]
    assert abbreviation_entries(
        "",
        [
            {"label": "Short word", "value": "abvn"},
            {"label": "Full expression", "value": "Abbreviation"},
        ],
    ) == [("abvn", "Abbreviation")]
    assert abbreviation_entries(
        "",
        [
            {"label": "Short word", "value": " spec   ops "},
            {"label": "Full expression", "value": "Special operations"},
        ],
    ) == [("spec   ops", "Special operations")]


def test_glossary_ingestion_rejects_documents_without_entries(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        indexing_stages,
        "chunk_items",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                text="No glossary rows here.", structured_fields=[], chunk_type="text"
            )
        ],
    )
    state = {
        "payload": IngestJobPayload(
            job_id="job-1",
            doc_id="doc-1",
            file_path="glossary.pdf",
            group_path="/legal",
            effective_date=None,
            supersedes=[],
            clearance_level="NATO_RESTRICTED",
            doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
        ),
        "parsed_items": [],
        "metadata": {},
    }
    deps = SimpleNamespace(
        chunk_target_tokens=400,
        chunk_overlap_tokens=40,
        parent_max_tokens=1200,
    )

    caplog.set_level(logging.WARNING, logger=indexing_stages.__name__)
    with pytest.raises(RuntimeError, match="no recognized entries"):
        indexing_stages.chunk_text(state, deps)
    assert "Abbreviation glossary extraction yielded no recognized entries" in caplog.text
    assert "types={'text': 1}" in caplog.text


def test_glossary_ingestion_logs_rejected_term_and_reason(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        indexing_stages,
        "chunk_items",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                text="ABC — ABC", structured_fields=[], chunk_type="text", page_start=4
            )
        ],
    )
    state = {
        "payload": IngestJobPayload(
            job_id="job-1",
            doc_id="doc-1",
            file_path="glossary.pdf",
            group_path="/legal",
            effective_date=None,
            supersedes=[],
            clearance_level="NATO_RESTRICTED",
            doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
        ),
        "parsed_items": [],
        "metadata": {},
    }
    deps = SimpleNamespace(
        chunk_target_tokens=400,
        chunk_overlap_tokens=40,
        parent_max_tokens=1200,
    )

    caplog.set_level(logging.WARNING, logger=indexing_stages.__name__)
    with pytest.raises(RuntimeError, match="no recognized entries"):
        indexing_stages.chunk_text(state, deps)
    assert "'term': 'ABC'" in caplog.text
    assert "'page': 4" in caplog.text
    assert "full expression matches the abbreviation" in caplog.text


def test_glossary_entries_are_staged_without_vectors_and_keep_source_page() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class Backend:
        def stage_index_generation(self, **kwargs: Any) -> None:
            calls.append(("stage", kwargs))

        def verify_index_generation(self, **kwargs: Any) -> None:
            calls.append(("verify", kwargs))

        def update_job(self, **kwargs: Any) -> None:
            calls.append(("progress", kwargs))

    state = {
        "payload": IngestJobPayload(
            job_id="job-1",
            doc_id="doc-1",
            file_path="glossary.pdf",
            group_path="/legal",
            effective_date=None,
            supersedes=[],
            clearance_level="NATO_RESTRICTED",
            doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
        ),
        "file_bytes": b"glossary",
        "metadata": {},
        "claims": [],
        "abbreviation_entries": [
            {
                "abbreviation": "AD",
                "expansion": "Assistant Director",
                "source_page": 7,
            }
        ],
    }
    deps = SimpleNamespace(
        backend=Backend(),
        chunk_target_tokens=400,
        chunk_overlap_tokens=40,
        parent_max_tokens=1200,
        ingestion_quality_preset="fast",
    )

    indexing_stages.stage_abbreviation_glossary(state, deps)

    assert calls[0][0] == "stage"
    assert calls[0][1]["expected_point_count"] == 0
    assert calls[0][1]["vector_dimension"] == 0
    assert calls[0][1]["abbreviation_entries"] == state["abbreviation_entries"]
    assert [name for name, _kwargs in calls] == ["stage", "verify", "progress"]
    assert calls[-1][1]["stage_progress"]["unit"] == "metadata"


def test_glossary_chunking_records_first_source_page(monkeypatch) -> None:
    monkeypatch.setattr(
        indexing_stages,
        "chunk_items",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                text="AD — Assistant Director",
                structured_fields=[],
                page_start=7,
                page=7,
            )
        ],
    )

    class Backend:
        def update_job(self, **_kwargs: Any) -> None:
            pass

    state = {
        "payload": IngestJobPayload(
            job_id="job-1",
            doc_id="doc-1",
            file_path="glossary.pdf",
            group_path="/legal",
            effective_date=None,
            supersedes=[],
            doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
        ),
        "parsed_items": [],
        "metadata": {},
    }
    deps = SimpleNamespace(
        backend=Backend(),
        chunk_target_tokens=400,
        chunk_overlap_tokens=40,
        parent_max_tokens=1200,
    )

    indexing_stages.chunk_text(state, deps)

    assert state["claims"] == []
    assert state["abbreviation_entries"] == [
        {
            "abbreviation": "AD",
            "expansion": "Assistant Director",
            "source_page": 7,
        }
    ]


def test_glossary_chunking_recovers_flattened_pdf_table_rows() -> None:
    chunks = [
        SimpleNamespace(
            text=(
                "Short word Full expression\n"
                "abvn Abbreviation\nAA Above Average\n"
                "TDN Tradesman\nTDN Tradesmen"
            ),
            structured_fields=[],
            page=1,
            chunk_type="table",
        ),
        SimpleNamespace(
            text="NTA Native Table Audit\n\nOwner note: review annually.",
            structured_fields=[],
            page=1,
            chunk_type="text",
        ),
    ]

    assert indexing_stages._abbreviation_entries_with_pages(chunks) == [
        {
            "abbreviation": "ABVN",
            "expansion": "Abbreviation",
            "source_page": 1,
        },
        {
            "abbreviation": "AA",
            "expansion": "Above Average",
            "source_page": 1,
        },
        {"abbreviation": "TDN", "expansion": "Tradesman", "source_page": 1},
        {"abbreviation": "TDN", "expansion": "Tradesmen", "source_page": 1},
        {
            "abbreviation": "NTA",
            "expansion": "Native Table Audit",
            "source_page": 1,
        },
    ]


def test_glossary_chunking_recovers_headerless_tables_split_across_pages() -> None:
    chunks = [
        SimpleNamespace(
            text=(
                "Table 2 - No Header\n"
                "| ML | Machine Learning |\n"
                "| --- | --- |\n"
                "| ner | Named Entity Recognition |"
            ),
            structured_fields=[],
            page=1,
            chunk_type="table",
        ),
        SimpleNamespace(
            text="Table 2 - No Header\ntls Transport Layer Security Ui User Interface",
            structured_fields=[],
            page=2,
            chunk_type="table",
        ),
        SimpleNamespace(
            text="Row: Ui\nValue: UserInterface",
            structured_fields=[
                {"label": "tls", "value": "Ui"},
                {"label": "TransportLayerSecurity", "value": "UserInterface"},
            ],
            page=2,
            chunk_type="table_row",
        ),
    ]

    assert indexing_stages._abbreviation_entries_with_pages(chunks) == [
        {"abbreviation": "ML", "expansion": "Machine Learning", "source_page": 1},
        {
            "abbreviation": "NER",
            "expansion": "Named Entity Recognition",
            "source_page": 1,
        },
        {
            "abbreviation": "TLS",
            "expansion": "Transport Layer Security",
            "source_page": 2,
        },
        {"abbreviation": "UI", "expansion": "User Interface", "source_page": 2},
    ]

def test_worker_import_callback_uses_internal_glossary_route(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def request_json(_base_url, path, **kwargs):
        captured.update(path=path, **kwargs)
        return {"imported_count": 1}

    monkeypatch.setattr(backend_adapter, "request_json", request_json)
    client = BackendInternalClient(
        base_url="http://backend.test",
        service_token="test-token",
        timeout_seconds=1,
    )

    client.replace_abbreviation_glossary(
        document_id="doc-1",
        entries=[("AD", "Assistant Director")],
    )

    assert captured["path"] == "/internal/abbreviation-glossaries/import"
    assert captured["payload"] == {
        "document_id": "doc-1",
        "entries": [{"abbreviation": "AD", "expansion": "Assistant Director"}],
    }
    assert captured["headers"] == {"X-Service-Token": "test-token"}
