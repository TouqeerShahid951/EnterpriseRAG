"""Small JSON HTTP helper for worker adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass
class ServiceRequestError(Exception):
    service: str
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        return self.message


def request_json(
    base_url: str,
    path: str,
    *,
    service: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"content-type": "application/json", "accept": "application/json"}
    request_headers.update(headers or {})
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=data,
        method=method,
        headers=request_headers,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ServiceRequestError(service, detail or exc.reason, exc.code) from exc
    except URLError as exc:
        raise ServiceRequestError(service, str(exc.reason)) from exc
    except TimeoutError as exc:
        raise ServiceRequestError(service, "request timed out") from exc
    except OSError as exc:
        raise ServiceRequestError(service, str(exc)) from exc

    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except JSONDecodeError as exc:
        raise ServiceRequestError(service, "response was not valid JSON", 502) from exc
    if not isinstance(value, dict):
        raise ServiceRequestError(service, "expected a JSON object response", 502)
    return value
