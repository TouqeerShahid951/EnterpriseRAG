"""LangGraph ingestion graph for native PDF jobs."""

from __future__ import annotations

from ..messages import IngestJobPayload
from .state import IngestDependencies, IngestState
from .steps import (
    chunk_text,
    commit_supersession,
    download_file,
    embed_chunks,
    extract_text,
    generate_metadata,
    mark_complete,
    mark_processing,
    persist_claims,
    persist_document_metadata,
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
    graph.add_node("mark_processing", lambda state: mark_processing(state, deps))
    graph.add_node("download_file", lambda state: download_file(state, deps))
    graph.add_node("extract_text", lambda state: extract_text(state, deps))
    graph.add_node("generate_metadata", lambda state: generate_metadata(state, deps))
    graph.add_node("persist_document_metadata", lambda state: persist_document_metadata(state, deps))
    graph.add_node("chunk_text", lambda state: chunk_text(state, deps))
    graph.add_node("embed_chunks", lambda state: embed_chunks(state, deps))
    graph.add_node("upsert_qdrant", lambda state: upsert_qdrant(state, deps))
    graph.add_node("persist_claims", lambda state: persist_claims(state, deps))
    graph.add_node("commit_supersession", lambda state: commit_supersession(state, deps))
    graph.add_node("mark_complete", lambda state: mark_complete(state, deps))


def _add_edges(graph, *, end_node: str) -> None:
    graph.add_edge("mark_processing", "download_file")
    graph.add_edge("download_file", "extract_text")
    graph.add_edge("extract_text", "generate_metadata")
    graph.add_edge("generate_metadata", "persist_document_metadata")
    graph.add_edge("persist_document_metadata", "chunk_text")
    graph.add_edge("chunk_text", "persist_claims")
    graph.add_edge("persist_claims", "embed_chunks")
    graph.add_edge("embed_chunks", "upsert_qdrant")
    graph.add_edge("upsert_qdrant", "commit_supersession")
    graph.add_edge("commit_supersession", "mark_complete")
    graph.add_edge("mark_complete", end_node)
