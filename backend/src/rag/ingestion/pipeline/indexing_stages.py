"""Chunking, embedding, and generation-safe indexing stages."""

import hashlib
import json

from ..chunking import chunk_items
from ..indexing.claims import build_claim_records
from ..indexing.metadata_text import build_embedding_texts
from ..indexing.payloads import build_qdrant_points
from ..publication.models import aggregate_generation_hash, generation_id_for_job
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
    generation_id = generation_id_for_job(state["payload"].job_id)
    state["index_generation_id"] = generation_id
    state["points"] = build_qdrant_points(
        job=state["payload"],
        chunks=state["chunks"],
        vectors=state["vectors"],
        sparse_vectors=state["sparse_vectors"],
        metadata=state["metadata"],
        file_bytes=state["file_bytes"],
        claims=state["claims"],
        index_generation_id=generation_id,
    )
    item_hashes = [
        str(point["payload"]["generation_item_hash"])
        for point in state["points"]
        if isinstance(point.get("payload"), dict)
    ]
    deps.backend.stage_index_generation(
        job_id=state["payload"].job_id,
        generation_id=generation_id,
        input_hash=hashlib.sha256(state["file_bytes"]).hexdigest(),
        configuration_digest=_configuration_digest(deps),
        expected_point_count=len(state["points"]),
        expected_item_hash=aggregate_generation_hash(item_hashes),
        vector_dimension=len(state["vectors"][0]),
        metadata=state["metadata"],
        claims=state["claims"],
        supersedes=state["payload"].supersedes,
        warnings=state.get("warnings", []),
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
    generation_id = state["index_generation_id"]
    state["upsert_count"] = deps.qdrant.stage_generation(
        generation_id=generation_id,
        points=state["points"],
        guard=lambda: raise_if_job_cancelled(deps, job_id),
    )
    deps.qdrant.verify_generation(
        generation_id=generation_id,
        expected_point_count=state["upsert_count"],
        expected_item_hash=aggregate_generation_hash(
            str(point["payload"]["generation_item_hash"])
            for point in state["points"]
            if isinstance(point.get("payload"), dict)
        ),
        vector_dimension=len(state["vectors"][0]),
    )
    deps.backend.verify_index_generation(job_id=job_id, generation_id=generation_id)
    deps.qdrant.publish_generation(
        generation_id,
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


def activate_generation(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.backend.activate_index_generation(
        job_id=state["payload"].job_id,
        generation_id=state["index_generation_id"],
    )
    return state


def _configuration_digest(deps: IngestDependencies) -> str:
    payload = {
        "chunk_target_tokens": deps.chunk_target_tokens,
        "chunk_overlap_tokens": deps.chunk_overlap_tokens,
        "parent_max_tokens": deps.parent_max_tokens,
        "quality_preset": deps.ingestion_quality_preset,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
