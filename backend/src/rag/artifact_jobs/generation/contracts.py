"""Artifact-owned contract for structured content generation."""

from __future__ import annotations

from typing import Protocol
from collections.abc import Callable
from rag.shared.contracts.evidence import CitationClaim, SourceAnchor


class ArtifactJsonGenerator(Protocol):
    """Generate one JSON document for an artifact planning or composition prompt."""

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict[str, object] | None = None,
    ) -> str: ...

    def validate_evidence(self, claims: list[CitationClaim], sources: list[SourceAnchor], *,
                          question: str, answer: str, model: str, deadline: float,
                          check_cancelled: Callable[[], None], max_calls: int,
                          context_tokens: int, output_tokens: int) -> tuple[list[CitationClaim], int]: ...


class ArtifactGenerationError(RuntimeError):
    """A configured generation provider could not complete the request."""

    def __init__(self, service: str, status_code: int | None = None) -> None:
        self.service = service
        self.status_code = status_code
        status = f" (status {status_code})" if status_code is not None else ""
        super().__init__(f"artifact generation provider {service} failed{status}")
