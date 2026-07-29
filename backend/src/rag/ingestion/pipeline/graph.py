"""Ordered ingestion workflow for native PDF jobs."""

from __future__ import annotations

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE

from ..contracts import IngestJobPayload
from ..errors import IngestJobCancelled
from .state import IngestDependencies, IngestState
from .steps import (
    chunk_text,
    activate_generation,
    download_file,
    embed_chunks,
    extract_text,
    generate_metadata,
    mark_processing,
    stage_abbreviation_glossary,
    upsert_qdrant,
)


def run_ingest_graph(payload: IngestJobPayload, deps: IngestDependencies) -> IngestState:
    state: IngestState = {"payload": payload}
    common_steps = (
        mark_processing,
        download_file,
        extract_text,
        generate_metadata,
        chunk_text,
    )
    publication_steps = (
        (stage_abbreviation_glossary, activate_generation)
        if payload.doc_type == ABBREVIATION_GLOSSARY_DOC_TYPE
        else (embed_chunks, upsert_qdrant, activate_generation)
    )
    for step in (*common_steps, *publication_steps):
        _raise_if_cancelled(state, deps)
        state = step(state, deps)
        _raise_if_cancelled(state, deps)
    return state


def _raise_if_cancelled(state: IngestState, deps: IngestDependencies) -> None:
    job_id = state["payload"].job_id
    ensure_lease = getattr(deps.backend, "ensure_lease", None)
    if callable(ensure_lease):
        ensure_lease(job_id)
    get_status = getattr(deps.backend, "get_job_status", None)
    if not callable(get_status):
        return
    if get_status(job_id=job_id).status == "cancelled":
        raise IngestJobCancelled(job_id=job_id)
