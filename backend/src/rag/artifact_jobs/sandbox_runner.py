"""Artifact sandbox runner ports and adapters."""

from __future__ import annotations

import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .sandbox_contracts import ArtifactSandboxRenderRequest, ArtifactSandboxRenderResult


class ArtifactSandboxRunner(Protocol):
    def render(self, request: ArtifactSandboxRenderRequest) -> ArtifactSandboxRenderResult: ...


class HttpArtifactSandboxRunner:
    def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def render(self, request: ArtifactSandboxRenderRequest) -> ArtifactSandboxRenderResult:
        payload = request.model_dump_json().encode("utf-8")
        http_request = Request(
            f"{self.base_url}/v1/render",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:4000]
            raise RuntimeError(f"artifact sandbox returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"artifact sandbox unavailable: {exc.reason}") from exc
        try:
            return ArtifactSandboxRenderResult.model_validate(json.loads(body))
        except ValueError as exc:
            raise RuntimeError("artifact sandbox returned invalid JSON") from exc


class InMemoryArtifactSandboxRunner:
    def __init__(self, result: ArtifactSandboxRenderResult | None = None, error: Exception | None = None) -> None:
        self.result = result or ArtifactSandboxRenderResult()
        self.error = error
        self.requests: list[ArtifactSandboxRenderRequest] = []

    def render(self, request: ArtifactSandboxRenderRequest) -> ArtifactSandboxRenderResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result
