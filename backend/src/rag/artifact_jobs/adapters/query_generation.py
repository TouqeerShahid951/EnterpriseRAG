"""Query-runtime adapter for artifact JSON generation."""

from __future__ import annotations

from ...query.http import ServiceRequestError
from ...query.inference import InferenceClient
from ..generation import ArtifactGenerationError
from collections.abc import Callable
from rag.shared.contracts.evidence import CitationClaim, SourceAnchor
from rag.query.evidence_validation import VerificationBudget, validate_claims


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
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict[str, object] | None = None,
    ) -> str:
        try:
            return self._client.generate_json(
                prompt=prompt,
                model=model,
                system=system,
                **({"timeout_seconds": timeout_seconds} if timeout_seconds is not None else {}),
                **({"max_tokens": max_tokens} if max_tokens is not None else {}),
                **({"json_schema": json_schema} if json_schema is not None else {}),
            )
        except ServiceRequestError as exc:
            raise ArtifactGenerationError(
                exc.service,
                exc.status_code,
            ) from exc

    def validate_evidence(self, claims: list[CitationClaim], sources: list[SourceAnchor], *,
                          question: str, answer: str, model: str, deadline: float,
                          check_cancelled: Callable[[], None], max_calls: int,
                          context_tokens: int, output_tokens: int) -> tuple[list[CitationClaim], int]:
        def generate(**kwargs: object) -> str:
            check_cancelled()
            try:
                result = self._client.judge_faithfulness(model=model, **kwargs)
            except ServiceRequestError as exc:
                raise ValueError("citation_provider_unavailable") from exc
            check_cancelled()
            return result
        budget = VerificationBudget(deadline, max_calls=max_calls, context_tokens=context_tokens, output_tokens=output_tokens)
        checked = validate_claims(claims, sources, question=question, answer=answer, generate=generate, budget=budget)
        return checked, budget.calls
