"""Workspace ingestion configuration contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

@dataclass(frozen=True)
class IngestConfigRecord:
    worker_concurrency: int = 1
    ocr_review_confidence_threshold: float = 0.9
    pdf_image_review_threshold: int = 64
    vision_layout_repair_enabled: bool = False
    graph_enrichment_enabled: bool = False
    updated_by: str | None = None
    updated_at: datetime | None = None
    source: str = "workspace"


class IngestConfigRepository(Protocol):
    def get_active(self) -> IngestConfigRecord | None: ...

    def save_active(self, config: IngestConfigRecord) -> IngestConfigRecord: ...
