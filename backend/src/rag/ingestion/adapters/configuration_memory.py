"""In-memory adapter for workspace ingestion configuration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from ..configuration import IngestConfigRecord


class InMemoryIngestConfigRepository:
    def __init__(self) -> None:
        self.active: IngestConfigRecord | None = None

    def get_active(self) -> IngestConfigRecord | None:
        return self.active

    def save_active(self, config: IngestConfigRecord) -> IngestConfigRecord:
        self.active = replace(config, updated_at=datetime.now(UTC))
        return self.active
