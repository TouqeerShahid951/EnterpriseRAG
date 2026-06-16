"""Cancellation helpers for query requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from inspect import Parameter, signature
from threading import Event, Lock
from typing import Any, TypeVar


class QueryCancelled(Exception):
    """Raised when a query request has been cancelled by the client."""


class QueryCancellationToken:
    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._closers: list[Callable[[], object]] = []

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            closers = list(self._closers)
            self._closers.clear()

        for closer in closers:
            with suppress(Exception):
                closer()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise QueryCancelled()

    def register_closer(self, closer: Callable[[], object]) -> Callable[[], None]:
        should_close = False
        with self._lock:
            if self._event.is_set():
                should_close = True
            else:
                self._closers.append(closer)

        if should_close:
            with suppress(Exception):
                closer()

        def unregister() -> None:
            with self._lock:
                with suppress(ValueError):
                    self._closers.remove(closer)

        return unregister


T = TypeVar("T")


def cancellation_token_from_context(ctx: Mapping[str, object]) -> QueryCancellationToken | None:
    token = ctx.get("cancellation_token")
    return token if isinstance(token, QueryCancellationToken) else None


def call_with_optional_cancellation(
    fn: Callable[..., T],
    cancellation_token: QueryCancellationToken | None,
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    if cancellation_token is None:
        return fn(*args, **kwargs)
    cancellation_token.raise_if_cancelled()
    if _accepts_cancellation_token(fn):
        return fn(*args, cancellation_token=cancellation_token, **kwargs)
    return fn(*args, **kwargs)


def _accepts_cancellation_token(fn: Callable[..., object]) -> bool:
    try:
        parameters = signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if "cancellation_token" in parameters:
        return True
    return any(parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values())
