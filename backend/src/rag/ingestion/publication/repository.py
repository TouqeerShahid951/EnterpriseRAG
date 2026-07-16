"""Narrow persistence contract for generation publication."""

from __future__ import annotations

from typing import Any, Protocol

from .models import IndexGeneration


class IndexPublicationRepository(Protocol):
    def stage(
        self,
        *,
        generation_id: str,
        job_id: str,
        run_token: str,
        input_hash: str,
        configuration_digest: str,
        expected_point_count: int,
        expected_item_hash: str,
        vector_dimension: int,
        staged_metadata: dict[str, Any],
    ) -> IndexGeneration: ...

    def mark_verified(
        self, *, generation_id: str, job_id: str, run_token: str
    ) -> IndexGeneration: ...

    def activate(
        self, *, generation_id: str, job_id: str, run_token: str
    ) -> IndexGeneration: ...

    def cancel_building(self, *, job_id: str) -> str | None: ...

    def active_generation_ids(
        self,
        document_ids: list[str],
        current_only: bool,
    ) -> dict[str, str | None]: ...

    def list_retiring(self, *, limit: int) -> tuple[IndexGeneration, ...]: ...

    def mark_retired(self, generation_id: str) -> bool: ...
