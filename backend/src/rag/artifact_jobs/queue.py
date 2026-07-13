"""Queue contract for asynchronous document generation."""

from __future__ import annotations

from typing import Protocol


class ArtifactJobQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...
