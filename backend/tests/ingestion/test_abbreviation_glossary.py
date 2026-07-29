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


def test_glossary_ingestion_rejects_documents_without_entries(monkeypatch) -> None:
    monkeypatch.setattr(
        indexing_stages,
        "chunk_items",
        lambda *_args, **_kwargs: [
            SimpleNamespace(text="No glossary rows here.", structured_fields=[])
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

    with pytest.raises(RuntimeError, match="no recognized entries"):
        indexing_stages.chunk_text(state, deps)


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
        SimpleNamespace(text="Abbreviation Full Form", structured_fields=[], page=1),
        SimpleNamespace(text="NTX Native Table Extraction", structured_fields=[], page=1),
        SimpleNamespace(
            text="NTA Native Table Audit\n\nOwner note: review annually.",
            structured_fields=[],
            page=1,
        ),
    ]

    assert indexing_stages._abbreviation_entries_with_pages(chunks) == [
        {
            "abbreviation": "NTX",
            "expansion": "Native Table Extraction",
            "source_page": 1,
        },
        {
            "abbreviation": "NTA",
            "expansion": "Native Table Audit",
            "source_page": 1,
        },
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
