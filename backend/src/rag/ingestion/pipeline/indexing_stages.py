"""Persistence, chunking, embedding, and indexing stages."""

from ..chunking import chunk_items
from ..indexing.claims import build_claim_records
from ..indexing.metadata_text import build_embedding_texts
from ..indexing.payloads import build_qdrant_points
from .progress import (
    bounded_progress,
    items_progress,
    raise_if_job_cancelled,
    should_report_progress,
)
from .state import IngestDependencies, IngestState


def mark_processing(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.backend.update_job(
        job_id=state["payload"].job_id, status="processing", progress_pct=5
    )
    return state


def download_file(state: IngestState, deps: IngestDependencies) -> IngestState:
    state["file_bytes"] = deps.storage.read(state["payload"].file_path)
    deps.backend.update_job(
        job_id=state["payload"].job_id, status="processing", progress_pct=20
    )
    return state


def persist_document_metadata(
    state: IngestState, deps: IngestDependencies
) -> IngestState:
    deps.backend.save_document_metadata(
        doc_id=state["payload"].doc_id, metadata=state["metadata"]
    )
    deps.backend.update_job(
        job_id=state["payload"].job_id, status="processing", progress_pct=55
    )
    return state


def chunk_text(state: IngestState, deps: IngestDependencies) -> IngestState:
    state["chunks"] = chunk_items(
        state["parsed_items"],
        doc_id=state["payload"].doc_id,
        target_tokens=deps.chunk_target_tokens,
        overlap_tokens=deps.chunk_overlap_tokens,
        parent_max_tokens=deps.parent_max_tokens,
    )
    if not state["chunks"]:
        raise RuntimeError("document extraction produced no chunks")
    state["claims"] = build_claim_records(
        job=state["payload"],
        chunks=state["chunks"],
        metadata=state["metadata"],
    )
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=60,
        stage_progress=items_progress(
            "chunks",
            len(state["chunks"]),
            len(state["chunks"]),
            "Built retrieval chunks",
        ),
    )
    return state


def persist_claims(state: IngestState, deps: IngestDependencies) -> IngestState:
    state["conflicted_claim_ids"] = deps.backend.save_ingest_claims(
        doc_id=state["payload"].doc_id,
        claims=state["claims"],
    )
    deps.backend.update_job(
        job_id=state["payload"].job_id, status="processing", progress_pct=65
    )
    return state


def embed_chunks(state: IngestState, deps: IngestDependencies) -> IngestState:
    chunks = state["chunks"]
    embedding_texts = build_embedding_texts(
        file_path=state["payload"].file_path,
        chunks=chunks,
        metadata=state["metadata"],
    )

    def report(index: int, total: int) -> None:
        raise_if_job_cancelled(deps, state["payload"].job_id)
        if should_report_progress(index, len(chunks)):
            deps.backend.update_job(
                job_id=state["payload"].job_id,
                status="processing",
                progress_pct=bounded_progress(65, 74, index, len(chunks)),
                stage_progress=items_progress(
                    "chunks",
                    index,
                    len(chunks),
                    f"Embedding chunk {index} of {len(chunks)}",
                ),
            )

    state["vectors"] = deps.ollama.embed_many(embedding_texts, progress=report)
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=75,
        stage_progress=items_progress(
            "vectors", len(chunks), len(chunks), "Generating sparse vectors"
        ),
    )
    state["sparse_vectors"] = deps.sparse_embedder.embed_many(embedding_texts)
    state["points"] = build_qdrant_points(
        job=state["payload"],
        chunks=state["chunks"],
        vectors=state["vectors"],
        sparse_vectors=state["sparse_vectors"],
        metadata=state["metadata"],
        file_bytes=state["file_bytes"],
        claims=state["claims"],
        conflicted_claim_ids=state.get("conflicted_claim_ids", []),
    )
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=78,
        stage_progress=items_progress(
            "vectors",
            len(state["points"]),
            len(state["points"]),
            "Prepared vectors for indexing",
        ),
    )
    return state


def upsert_qdrant(state: IngestState, deps: IngestDependencies) -> IngestState:
    job_id = state["payload"].job_id
    deps.qdrant.ensure_collection(len(state["vectors"][0]))
    raise_if_job_cancelled(deps, job_id)
    deps.backend.update_job(
        job_id=job_id,
        status="processing",
        progress_pct=82,
        stage_progress=items_progress(
            "vectors", 0, len(state["points"]), "Writing vectors to Qdrant"
        ),
    )
    state["upsert_count"] = deps.qdrant.replace_document(
        doc_id=state["payload"].doc_id,
        points=state["points"],
        guard=lambda: raise_if_job_cancelled(deps, job_id),
    )
    deps.backend.update_job(
        job_id=job_id,
        status="processing",
        progress_pct=92,
        stage_progress=items_progress(
            "vectors",
            state["upsert_count"],
            len(state["points"]),
            "Indexed vectors",
        ),
    )
    return state


def commit_supersession(state: IngestState, deps: IngestDependencies) -> IngestState:
    if state["payload"].supersedes:
        job_id = state["payload"].job_id
        deps.qdrant.mark_documents_not_current(
            state["payload"].supersedes,
            guard=lambda: raise_if_job_cancelled(deps, job_id),
        )
        deps.backend.commit_supersession(
            new_doc_id=state["payload"].doc_id,
            supersedes=state["payload"].supersedes,
        )
    return state


def mark_complete(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="complete",
        progress_pct=100,
        warnings=state.get("warnings", []),
    )
    return state
