"""Keep ingestion producers behind the durable delivery owner."""

from _dependency_scanner import RAG_ROOT


INGEST_PRODUCERS = (
    RAG_ROOT / "documents" / "upload" / "service.py",
    RAG_ROOT / "documents" / "lifecycle" / "reingestion_service.py",
    RAG_ROOT / "documents" / "lifecycle" / "service.py",
    RAG_ROOT / "ingestion" / "folders" / "dispatch.py",
    RAG_ROOT / "ingestion" / "review" / "human_routes.py",
    RAG_ROOT / "ingestion" / "review" / "image_routes.py",
    RAG_ROOT / "ingestion" / "recovery.py",
    RAG_ROOT / "ops" / "reindex_documents_cli.py",
)


def test_ingest_producers_do_not_publish_directly_to_the_queue() -> None:
    offenders = [
        path.relative_to(RAG_ROOT)
        for path in INGEST_PRODUCERS
        if ".enqueue(" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
