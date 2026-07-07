from rag.services.ingest_queue import IngestQueueMessage, _message_payload
from rag_ingestion.chunking import TextChunk
from rag_ingestion.indexing.payloads import build_qdrant_points
from rag_ingestion.indexing.sparse import SparseVector
from rag_ingestion.messages import IngestJobPayload


def test_qdrant_points_include_shared_acl_group_paths() -> None:
    job = IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="memory://Shared.pdf",
        group_path="/legal",
        acl_group_paths=["/finance", "/legal", "/finance"],
        effective_date=None,
        supersedes=[],
    )
    chunk = TextChunk(
        index=0,
        page=1,
        text="Shared document text",
        parent_chunk_id="doc-1:parent:0",
        parent_text="Shared document text",
        chunk_type="text",
        section_title=None,
        page_start=1,
        page_end=1,
    )

    points = build_qdrant_points(
        job=job,
        chunks=[chunk],
        vectors=[[0.1, 0.2, 0.3]],
        sparse_vectors=[SparseVector(indices=[], values=[])],
        metadata={},
        file_bytes=b"shared document",
    )

    assert points[0]["payload"]["group_path"] == "/legal"
    assert points[0]["payload"]["acl_group_paths"] == ["/legal", "/finance"]


def test_qdrant_points_include_chunk_claims_and_entity_hints() -> None:
    job = IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="memory://Shared.pdf",
        group_path="/legal",
        effective_date=None,
        supersedes=[],
    )
    chunk = TextChunk(
        index=0,
        page=1,
        text="Acme Corp operates Project Apollo.",
        parent_chunk_id="doc-1:parent:0",
        parent_text="Acme Corp operates Project Apollo.",
        chunk_type="text",
        section_title=None,
        page_start=1,
        page_end=1,
    )

    points = build_qdrant_points(
        job=job,
        chunks=[chunk],
        vectors=[[0.1, 0.2, 0.3]],
        sparse_vectors=[SparseVector(indices=[], values=[])],
        metadata={
            "named_entities": [
                {"text": "Acme Corp", "type": "organization"},
                {"text": "Not In Chunk", "type": "organization"},
            ]
        },
        file_bytes=b"shared document",
        claims=[
            {
                "id": "claim-1",
                "doc_id": "doc-1",
                "chunk_id": "doc-1:0",
                "entity": "Acme Corp",
                "attribute": "operates",
                "value": "Project Apollo",
            }
        ],
    )

    payload = points[0]["payload"]
    assert payload["claim_ids"] == ["claim-1"]
    assert payload["claims"][0]["entity"] == "Acme Corp"
    assert payload["named_entities"] == [{"text": "Acme Corp", "type": "organization", "start": None, "end": None}]


def test_qdrant_points_preserve_generated_topics_separately() -> None:
    job = IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="memory://Shared.pdf",
        group_path="/legal",
        effective_date=None,
        supersedes=[],
    )
    chunk = TextChunk(
        index=0,
        page=1,
        text="Shared document text",
        parent_chunk_id="doc-1:parent:0",
        parent_text="Shared document text",
        chunk_type="text",
        section_title=None,
        page_start=1,
        page_end=1,
    )

    points = build_qdrant_points(
        job=job,
        chunks=[chunk],
        vectors=[[0.1, 0.2, 0.3]],
        sparse_vectors=[SparseVector(indices=[], values=[])],
        metadata={"topics": ["OCR"], "llm_topics": ["Handwriting recognition"]},
        file_bytes=b"shared document",
    )

    payload = points[0]["payload"]
    assert payload["topics"] == ["OCR"]
    assert payload["llm_topics"] == ["Handwriting recognition"]


def test_upload_quality_preset_roundtrips_through_queue_and_worker_payload() -> None:
    message = IngestQueueMessage(
        job_id="job-1",
        doc_id="doc-1",
        file_path="memory://policy.pdf",
        group_path="/legal",
        effective_date=None,
        supersedes=[],
        quality_preset="high_accuracy",
    )

    payload = _message_payload(message)
    job = IngestJobPayload.from_dict(payload)

    assert payload["quality_preset"] == "high_accuracy"
    assert job.quality_preset == "high_accuracy"
    assert IngestJobPayload.from_dict(job.to_dict()).quality_preset == "high_accuracy"
