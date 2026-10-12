"""Ordered ingestion workflow for native PDF jobs."""

from __future__ import annotations

import logging

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE

from ..contracts import IngestJobPayload
from ..errors import IngestJobCancelled
from .state import IngestDependencies, IngestState
from .indexing_stages import _configuration_digest
from .resume import refresh_review_context, restore_metadata_state, restore_parsed_state, restore_prepared_state
from .progress import items_progress
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

logger = logging.getLogger(__name__)


def run_ingest_graph(payload: IngestJobPayload, deps: IngestDependencies) -> IngestState:
    state: IngestState = {"payload": payload}
    common_steps = (mark_processing, download_file)
    publication_steps = (
        (stage_abbreviation_glossary, activate_generation)
        if payload.doc_type == ABBREVIATION_GLOSSARY_DOC_TYPE
        else (embed_chunks, upsert_qdrant, activate_generation)
    )
    for step in common_steps:
        _raise_if_cancelled(state, deps)
        state = step(state, deps)
        _raise_if_cancelled(state, deps)
    refresh_review_context(state, deps)
    _adopt_linked_checkpoints(state, deps)
    configuration_digest = (
        _configuration_digest(deps) if getattr(deps, "checkpoint", None) is not None else ""
    )
    restored = restore_prepared_state(state, deps, configuration_digest)
    if restored:
        logger.info("ingestion checkpoint restored job_id=%s stage=prepared chunks=%d", payload.job_id, len(state.get("chunks", [])))
        deps.backend.update_job(
            job_id=payload.job_id,
            status="processing",
            progress_pct=60,
            stage_progress=items_progress(
                "chunks",
                len(state.get("chunks", [])),
                len(state.get("chunks", [])),
                "Restored prepared ingestion checkpoint",
            ),
        )
    else:
        metadata_restored = restore_metadata_state(state, deps, _configuration_digest(deps, "metadata"))
        parsed_restored = metadata_restored or restore_parsed_state(state, deps, _configuration_digest(deps, "parsed"))
        restored = metadata_restored or parsed_restored
        if restored:
            logger.info(
                "ingestion checkpoint restored job_id=%s stage=%s",
                payload.job_id,
                "metadata" if metadata_restored else "parsed",
            )
        common_resume_steps = []
        if not parsed_restored:
            common_resume_steps.append(extract_text)
        if not metadata_restored:
            common_resume_steps.append(generate_metadata)
        common_resume_steps.append(chunk_text)
        for step in common_resume_steps:
            _raise_if_cancelled(state, deps)
            state = step(state, deps)
            _raise_if_cancelled(state, deps)
    if restored:
        _reregister_parser_provenance(state, deps)
    for step in publication_steps:
        _raise_if_cancelled(state, deps)
        state = step(state, deps)
        _raise_if_cancelled(state, deps)
    return state


def _reregister_parser_provenance(state: IngestState, deps: IngestDependencies) -> None:
    provenance = state.get("parser_provenance")
    record = getattr(deps.backend, "record_parser_provenance", None)
    if isinstance(provenance, dict) and provenance and callable(record):
        record(job_id=state["payload"].job_id, provenance=provenance)


def _adopt_linked_checkpoints(state: IngestState, deps: IngestDependencies) -> None:
    checkpoint = getattr(deps, "checkpoint", None)
    get_status = getattr(deps.backend, "get_job_status", None)
    if checkpoint is None or not callable(get_status):
        return
    snapshot = get_status(job_id=state["payload"].job_id)
    predecessor = getattr(snapshot, "retry_of_job_id", None)
    if predecessor:
        copied = checkpoint.adopt_predecessor(
            job_id=state["payload"].job_id,
            document_id=state["payload"].doc_id,
            predecessor_job_id=predecessor,
        )
        logger.info(
            "ingestion checkpoints adopted job_id=%s predecessor_job_id=%s references=%d",
            state["payload"].job_id,
            predecessor,
            copied,
        )


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
