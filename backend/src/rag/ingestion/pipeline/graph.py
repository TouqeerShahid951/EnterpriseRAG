"""LangGraph ingestion graph for native PDF jobs."""

from __future__ import annotations

from collections.abc import Callable

from ..errors import IngestJobCancelled
from ..contracts import IngestJobPayload
from .state import IngestDependencies, IngestState
from .steps import (
    chunk_text,
    activate_generation,
    download_file,
    embed_chunks,
    extract_text,
    generate_metadata,
    mark_processing,
    upsert_qdrant,
)


def run_ingest_graph(payload: IngestJobPayload, deps: IngestDependencies) -> IngestState:
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise RuntimeError("langgraph package is required for ingestion graph execution") from exc

    graph = StateGraph(IngestState)
    _add_nodes(graph, deps)
    graph.set_entry_point("mark_processing")
    _add_edges(graph, end_node=END)
    return graph.compile().invoke({"payload": payload})


def _add_nodes(graph, deps: IngestDependencies) -> None:
    graph.add_node("mark_processing", _cancellable(mark_processing, deps))
    graph.add_node("download_file", _cancellable(download_file, deps))
    graph.add_node("extract_text", _cancellable(extract_text, deps))
    graph.add_node("generate_metadata", _cancellable(generate_metadata, deps))
    graph.add_node("chunk_text", _cancellable(chunk_text, deps))
    graph.add_node("embed_chunks", _cancellable(embed_chunks, deps))
    graph.add_node("upsert_qdrant", _cancellable(upsert_qdrant, deps))
    graph.add_node("activate_generation", _cancellable(activate_generation, deps))


def _add_edges(graph, *, end_node: str) -> None:
    graph.add_edge("mark_processing", "download_file")
    graph.add_edge("download_file", "extract_text")
    graph.add_edge("extract_text", "generate_metadata")
    graph.add_edge("generate_metadata", "chunk_text")
    graph.add_edge("chunk_text", "embed_chunks")
    graph.add_edge("embed_chunks", "upsert_qdrant")
    graph.add_edge("upsert_qdrant", "activate_generation")
    graph.add_edge("activate_generation", end_node)


def _cancellable(
    step: Callable[[IngestState, IngestDependencies], IngestState],
    deps: IngestDependencies,
) -> Callable[[IngestState], IngestState]:
    def run(state: IngestState) -> IngestState:
        _raise_if_cancelled(state, deps)
        next_state = step(state, deps)
        _raise_if_cancelled(next_state, deps)
        return next_state

    return run


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
