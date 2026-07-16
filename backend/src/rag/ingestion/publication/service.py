"""Application boundary for a document index generation."""

from __future__ import annotations

from typing import Any

from .models import IndexGeneration
from .repository import IndexPublicationRepository


class IndexPublicationService:
    def __init__(self, repository: IndexPublicationRepository) -> None:
        self._repository = repository

    def stage(self, **kwargs: Any) -> IndexGeneration:
        return self._repository.stage(**kwargs)

    def mark_verified(self, **kwargs: Any) -> IndexGeneration:
        return self._repository.mark_verified(**kwargs)

    def activate(self, **kwargs: Any) -> IndexGeneration:
        return self._repository.activate(**kwargs)

    def cancel_building(self, *, job_id: str) -> str | None:
        return self._repository.cancel_building(job_id=job_id)

    def active_generation_ids(
        self,
        document_ids: list[str],
        current_only: bool,
    ) -> dict[str, str | None]:
        return self._repository.active_generation_ids(document_ids, current_only)

    def list_retiring(self, *, limit: int) -> tuple[IndexGeneration, ...]:
        return self._repository.list_retiring(limit=limit)

    def mark_retired(self, generation_id: str) -> bool:
        return self._repository.mark_retired(generation_id)
