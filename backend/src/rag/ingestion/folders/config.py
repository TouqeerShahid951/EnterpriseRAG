"""Feature-owned configuration values for scheduled folder ingestion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FolderIngestionConfig:
    """Validated values supplied by an API or background composition root."""

    default_timezone: str
    sources_root: str
    snapshot_max_files: int
    snapshot_max_bytes: int
    upload_max_bytes: int
