"""HTTP adapter for validating an artifact job's execution context."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..execution import ArtifactPermissionChanged
from ..task_execution import ArtifactContextRejected


@dataclass(frozen=True)
class HttpArtifactContextValidator:
    base_url: str
    service_token: str
    timeout_seconds: float

    def validate(self, job_id: str) -> None:
        base_url = self.base_url or "http://api:8000"
        request = Request(
            f"{base_url.rstrip('/')}/internal/artifact-jobs/{job_id}/context",
            headers={"X-Service-Token": self.service_token},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise ArtifactContextRejected(
                        f"artifact job context rejected with status {response.status}"
                    )
        except HTTPError as exc:
            if exc.code in {401, 403, 409}:
                raise ArtifactPermissionChanged(
                    f"artifact job context rejected with status {exc.code}"
                ) from exc
            if exc.code in {408, 429} or exc.code >= 500:
                raise RuntimeError(
                    "backend unavailable while validating artifact job context "
                    f"(status {exc.code})"
                ) from exc
            raise ArtifactContextRejected(
                f"artifact job context rejected with status {exc.code}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                "backend unavailable while validating artifact job context"
            ) from exc
