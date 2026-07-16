"""Artifact-owned contract for structured content generation."""

from __future__ import annotations

from typing import Protocol


class ArtifactJsonGenerator(Protocol):
    """Generate one JSON document for an artifact planning or composition prompt."""

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
    ) -> str: ...


class ArtifactGenerationError(RuntimeError):
    """A configured generation provider could not complete the request."""

    def __init__(self, service: str, status_code: int | None = None) -> None:
        self.service = service
        self.status_code = status_code
        status = f" (status {status_code})" if status_code is not None else ""
        super().__init__(f"artifact generation provider {service} failed{status}")
