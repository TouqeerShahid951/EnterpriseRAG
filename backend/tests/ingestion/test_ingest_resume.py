from rag.ingestion.pipeline.resume import (
    logical_ranges,
    missing_ranges,
    text_chunk_from_dict,
    text_chunk_to_dict,
)
from rag.ingestion.chunking.chunker import TextChunk
from rag.ingestion.pipeline.indexing_stages import _resume_dense_vectors
from rag.ingestion.pipeline.resume import _review_fingerprint, restore_prepared_state
from rag.ingestion.pipeline import graph
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.checkpoints.models import CheckpointDescriptor
from rag.ingestion.checkpoints.service import CheckpointService, encode_payload


def test_missing_ranges_preserves_saved_batches() -> None:
    assert logical_ranges(40, 16) == [(0, 16), (16, 32), (32, 40)]
    assert missing_ranges(40, 16, {(0, 16)}) == [(16, 32), (32, 40)]


def test_missing_ranges_recomputes_partial_or_invalid_batches() -> None:
    assert missing_ranges(40, 16, {(0, 16), (16, 31), (32, 40)}) == [(16, 32)]


def test_chunk_round_trip_keeps_citation_targets() -> None:
    chunk = TextChunk(
        index=0,
        page=3,
        text="Clause 5",
        parent_chunk_id="doc:parent:0",
        parent_text="Clause 5",
        chunk_type="text",
        section_title="Agreement",
        page_start=3,
        page_end=3,
        citation_targets=[{"page": 3, "exact_text": "Clause 5", "bbox": [1, 2, 3, 4]}],
    )
    assert text_chunk_from_dict(text_chunk_to_dict(chunk)) == chunk


def test_dense_resume_calls_provider_only_for_missing_ranges() -> None:
    class Checkpoints:
        def __init__(self):
            self.committed = []

        def load(self, *, stage_key, **_kwargs):
            if stage_key == "dense:0:2":
                return SimpleNamespace(body_sha256="a" * 64), {"vectors": [[1.0, 0.0], [0.0, 1.0]]}
            return None

        def commit(self, **kwargs):
            self.committed.append(kwargs)

    class Ollama:
        def __init__(self):
            self.inputs = []

        def embed_many(self, texts, progress=None):
            self.inputs.append(list(texts))
            if progress:
                progress(len(texts), len(texts))
            return [[float(index), 1.0] for index, _ in enumerate(texts)]

    from types import SimpleNamespace

    checkpoints = Checkpoints()
    ollama = Ollama()
    deps = SimpleNamespace(
        checkpoint=checkpoints,
        ollama=ollama,
        embedding_batch_size=2,
        chunk_target_tokens=4,
        chunk_overlap_tokens=1,
        parent_max_tokens=8,
        ingestion_quality_preset="fast",
    )
    state = {"payload": SimpleNamespace(job_id="job", doc_id="doc")}
    reported = []
    vectors = _resume_dense_vectors(state, deps, ["a", "b", "c", "d", "e"], lambda current, total: reported.append((current, total)))

    assert ollama.inputs == [["c", "d"], ["e"]]
    assert len(vectors) == 5
    assert [item["range_start"] for item in checkpoints.committed] == [2, 4]


def test_checkpoint_body_checksum_is_verified_before_restore() -> None:
    body, decoded_size = encode_payload({"chunks": []})
    descriptor = CheckpointDescriptor(
        job_id="job",
        document_id="doc",
        stage_key="prepared",
        object_key="ingest-checkpoints/doc/job/prepared.bin",
        schema_version=1,
        body_sha256="0" * 64,
        compressed_size=len(body),
        decoded_size=decoded_size,
        upstream_sha256="1" * 64,
        configuration_digest="2" * 64,
    )
    try:
        CheckpointService.load_bytes(descriptor, body)
    except ValueError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("invalid checkpoint checksum was accepted")


def test_prepared_restore_rehydrates_ordered_chunks_and_metadata() -> None:
    chunk = TextChunk(
        index=0,
        page=1,
        text="saved",
        parent_chunk_id="doc:parent:0",
        parent_text="saved",
        chunk_type="text",
        section_title=None,
        page_start=1,
        page_end=1,
    )

    class Checkpoints:
        def load(self, **_kwargs):
            return SimpleNamespace(body_sha256="a" * 64), {
                "chunks": [text_chunk_to_dict(chunk)],
                "claims": [],
                "metadata": {"summary": "saved"},
                "embedding_texts": ["saved"],
                "embedding_ranges": [[0, 1]],
                "parser_provenance": {"parser": "pymupdf"},
                "warnings": [],
                "review_fingerprint": _review_fingerprint(SimpleNamespace(to_dict=lambda: {})),
            }

    from types import SimpleNamespace

    state = {
        "payload": SimpleNamespace(job_id="job", doc_id="doc"),
        "file_bytes": b"source",
    }
    assert restore_prepared_state(state, SimpleNamespace(checkpoint=Checkpoints()), "a" * 64)
    assert state["chunks"] == [chunk]
    assert state["metadata"] == {"summary": "saved"}
    assert state["embedding_texts"] == ["saved"]


def test_graph_skips_parse_and_metadata_when_prepared_checkpoint_exists(monkeypatch) -> None:
    from types import SimpleNamespace

    payload = IngestJobPayload(
        job_id="job",
        doc_id="doc",
        file_path="doc.pdf",
        group_path="/ops",
        effective_date=None,
        supersedes=[],
    )
    chunk = TextChunk(
        index=0,
        page=1,
        text="saved",
        parent_chunk_id="doc:parent:0",
        parent_text="saved",
        chunk_type="text",
        section_title=None,
        page_start=1,
        page_end=1,
    )

    class Backend:
        def update_job(self, **_kwargs):
            return None

        def get_job_status(self, *, job_id):
            return SimpleNamespace(status="processing", retry_of_job_id=None)

        def record_parser_provenance(self, **_kwargs):
            return None

    class Checkpoints:
        def adopt_predecessor(self, **_kwargs):
            return 0

        def load(self, *, stage_key, **_kwargs):
            if stage_key != "prepared":
                return None
            return SimpleNamespace(body_sha256="a" * 64), {
                "chunks": [text_chunk_to_dict(chunk)],
                "claims": [],
                "metadata": {},
                "embedding_texts": ["saved"],
                "embedding_ranges": [[0, 1]],
                "parser_provenance": {"parser": "pymupdf"},
                "warnings": [],
                "abbreviation_entries": [],
                "review_fingerprint": _review_fingerprint(payload),
            }

    def mark(state, _deps):
        return state

    def download(state, _deps):
        state["file_bytes"] = b"source"
        return state

    monkeypatch.setattr(graph, "mark_processing", mark)
    monkeypatch.setattr(graph, "download_file", download)
    monkeypatch.setattr(graph, "extract_text", lambda *_: (_ for _ in ()).throw(AssertionError("parse called")))
    monkeypatch.setattr(graph, "generate_metadata", lambda *_: (_ for _ in ()).throw(AssertionError("metadata called")))
    monkeypatch.setattr(graph, "chunk_text", lambda *_: (_ for _ in ()).throw(AssertionError("chunk called")))
    monkeypatch.setattr(graph, "embed_chunks", lambda state, _deps: state)
    monkeypatch.setattr(graph, "upsert_qdrant", lambda state, _deps: state)
    monkeypatch.setattr(graph, "activate_generation", lambda state, _deps: state)

    deps = SimpleNamespace(
        backend=Backend(),
        checkpoint=Checkpoints(),
        ollama=SimpleNamespace(),
        sparse_embedder=SimpleNamespace(),
        chunk_target_tokens=4,
        chunk_overlap_tokens=1,
        parent_max_tokens=8,
        ingestion_quality_preset="fast",
    )
    state = graph.run_ingest_graph(payload, deps)
    assert state["chunks"] == [chunk]
