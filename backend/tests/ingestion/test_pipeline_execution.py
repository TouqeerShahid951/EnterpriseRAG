from types import SimpleNamespace

import pytest

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.errors import IngestJobCancelled
from rag.ingestion.pipeline import graph as pipeline_graph


def test_pipeline_runs_in_order_and_stops_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_names = (
        "mark_processing",
        "download_file",
        "extract_text",
        "generate_metadata",
        "chunk_text",
        "embed_chunks",
        "upsert_qdrant",
        "activate_generation",
    )
    events: list[str] = []

    class Backend:
        status_checks = 0

        def ensure_lease(self, _job_id: str) -> None:
            events.append("lease")

        def get_job_status(self, *, job_id: str) -> SimpleNamespace:
            self.status_checks += 1
            events.append("status")
            return SimpleNamespace(
                status="cancelled" if self.status_checks == 8 else "processing"
            )

    def stage(name: str):
        def run(state, _deps):
            events.append(name)
            return state

        return run

    for name in stage_names:
        monkeypatch.setattr(pipeline_graph, name, stage(name))

    payload = IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="minio://bucket/doc.pdf",
        group_path="/ops",
        effective_date=None,
        supersedes=[],
    )
    with pytest.raises(IngestJobCancelled):
        pipeline_graph.run_ingest_graph(
            payload,
            SimpleNamespace(backend=Backend()),  # type: ignore[arg-type]
        )

    expected: list[str] = []
    for name in stage_names[:4]:
        expected.extend(("lease", "status", name, "lease", "status"))
    assert events == expected


def test_glossary_pipeline_skips_embedding_and_qdrant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def stage(name: str):
        def run(state, _deps):
            events.append(name)
            return state

        return run

    for name in (
        "mark_processing",
        "download_file",
        "extract_text",
        "generate_metadata",
        "chunk_text",
        "stage_abbreviation_glossary",
        "activate_generation",
    ):
        monkeypatch.setattr(pipeline_graph, name, stage(name))

    def unexpected(*_args, **_kwargs):
        raise AssertionError("glossary must not enter vector indexing")

    monkeypatch.setattr(pipeline_graph, "embed_chunks", unexpected)
    monkeypatch.setattr(pipeline_graph, "upsert_qdrant", unexpected)

    payload = IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="minio://bucket/glossary.pdf",
        group_path="/ops",
        effective_date=None,
        supersedes=[],
        doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
    )
    pipeline_graph.run_ingest_graph(
        payload,
        SimpleNamespace(backend=SimpleNamespace()),  # type: ignore[arg-type]
    )

    assert events == [
        "mark_processing",
        "download_file",
        "extract_text",
        "generate_metadata",
        "chunk_text",
        "stage_abbreviation_glossary",
        "activate_generation",
    ]
