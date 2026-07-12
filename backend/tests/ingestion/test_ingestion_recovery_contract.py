from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.recovery import ingest_queue_message
from rag.documents.adapters.memory import InMemoryDocumentRepository


def test_recovery_payload_preserves_document_clearance_and_access_groups() -> None:
    repo = InMemoryDocumentRepository()
    document = repo.create_document(
        title="Classified.pdf",
        source_id="source-1",
        group_path="/operations",
        clearance_level="COSMIC_TOP_SECRET",
        doc_type="policy",
        effective_date=None,
        expiry_date=None,
        description="Classified policy",
        pending_supersedes=[],
        content_hash="hash-1",
        uploaded_by="user-1",
        file_path="memory://classified.pdf",
        ingest_status="processing",
    )
    shared = repo.replace_document_shares(
        document.id,
        group_paths=["/leadership"],
        actor_id="user-1",
    )
    assert shared is not None
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="processing",
        progress_pct=25,
        origin="upload",
    )

    message = ingest_queue_message(shared, job)
    worker_payload = IngestJobPayload.from_dict(message.to_dict())

    assert worker_payload.clearance_level == "COSMIC_TOP_SECRET"
    assert worker_payload.acl_group_paths == ["/operations", "/leadership"]
