"""Query-runtime adapter for artifact JSON generation."""

from __future__ import annotations

from ...query.http import ServiceRequestError
from ...query.inference import InferenceClient
from ..generation import ArtifactGenerationError


class QueryRuntimeArtifactJsonGenerator:
    """Expose only the JSON-generation capability artifact jobs require."""

    def __init__(self, client: InferenceClient) -> None:
        self._client = client

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
    ) -> str:
        try:
            return self._client.generate_json(
                prompt=prompt,
                model=model,
                system=system,
            )
        except ServiceRequestError as exc:
            raise ArtifactGenerationError(
                exc.service,
                exc.status_code,
            ) from exc
