"""Ingestion pipeline public entrypoint."""

from __future__ import annotations

from ..contracts import IngestJobPayload
from .graph import IngestDependencies, run_ingest_graph


def run_ingestion_pipeline(payload: IngestJobPayload, dependencies: IngestDependencies):
    return run_ingest_graph(payload, dependencies)
