"""Checkpoint value objects shared by the API and ingestion worker."""

from __future__ import annotations

from dataclasses import dataclass


class CheckpointLeaseLost(ValueError):
    """The caller no longer owns a live ingestion job."""


@dataclass(frozen=True)
class CheckpointDescriptor:
    job_id: str
    document_id: str
    stage_key: str
    object_key: str
    schema_version: int
    body_sha256: str
    compressed_size: int
    decoded_size: int
    upstream_sha256: str
    configuration_digest: str
    range_start: int | None = None
    range_end: int | None = None
    model_identity: str | None = None
    vector_dimension: int | None = None
