"""Tiny JSON HTTP helper for local service adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .cancellation import QueryCancellationToken, QueryCancelled


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
    timeout_seconds: float = 30.0,
    cancellation_token: QueryCancellationToken | None = None,
) -> dict[str, Any]:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=data,
        method=method,
        headers={"content-type": "application/json", "accept": "application/json"},
    )

    unregister = None
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if cancellation_token is not None:
                unregister = cancellation_token.register_closer(response.close)
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise QueryCancelled() from exc
        detail = exc.read().decode("utf-8", errors="replace")
        raise ServiceRequestError(service, detail or exc.reason, exc.code) from exc
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise QueryCancelled() from exc
        raise ServiceRequestError(service, _transport_error_message(exc)) from exc
    finally:
        if unregister is not None:
            unregister()

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    if not raw:
        return {}

    try:
        value = json.loads(raw)
    except JSONDecodeError as exc:
        raise ServiceRequestError(service, "response was not valid JSON", 502) from exc
    if not isinstance(value, dict):
        raise ServiceRequestError(service, "expected a JSON object response", 502)
    return value


def stream_json_lines(
    base_url: str,
    path: str,
    *,
    service: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 30.0,
    cancellation_token: QueryCancellationToken | None = None,
) -> Iterator[dict[str, Any]]:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=data,
        method=method,
        headers={"content-type": "application/json", "accept": "application/x-ndjson, application/json"},
    )

    unregister = None
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if cancellation_token is not None:
                unregister = cancellation_token.register_closer(response.close)
            for raw_line in response:
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except JSONDecodeError as exc:
                    raise ServiceRequestError(service, "stream response included invalid JSON", 502) from exc
                if not isinstance(value, dict):
                    raise ServiceRequestError(service, "expected a JSON object stream item", 502)
                yield value
    except HTTPError as exc:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise QueryCancelled() from exc
        detail = exc.read().decode("utf-8", errors="replace")
        raise ServiceRequestError(service, detail or exc.reason, exc.code) from exc
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise QueryCancelled() from exc
        raise ServiceRequestError(service, _transport_error_message(exc)) from exc
    finally:
        if unregister is not None:
            unregister()

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()


def stream_sse_json(
    base_url: str,
    path: str,
    *,
    service: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 30.0,
    cancellation_token: QueryCancellationToken | None = None,
) -> Iterator[dict[str, Any]]:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=data,
        method=method,
        headers={"content-type": "application/json", "accept": "text/event-stream"},
    )
    unregister = None
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if cancellation_token is not None:
                unregister = cancellation_token.register_closer(response.close)
            for raw_line in response:
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
                line = raw_line.decode("utf-8").strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                raw_data = line[5:].strip()
                if raw_data == "[DONE]":
                    break
                try:
                    value = json.loads(raw_data)
                except JSONDecodeError as exc:
                    raise ServiceRequestError(service, "SSE stream included invalid JSON", 502) from exc
                if not isinstance(value, dict):
                    raise ServiceRequestError(service, "expected a JSON object SSE item", 502)
                yield value
    except HTTPError as exc:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise QueryCancelled() from exc
        detail = exc.read().decode("utf-8", errors="replace")
        raise ServiceRequestError(service, detail or exc.reason, exc.code) from exc
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise QueryCancelled() from exc
        raise ServiceRequestError(service, _transport_error_message(exc)) from exc
    finally:
        if unregister is not None:
            unregister()


def _transport_error_message(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return str(reason or exc)
