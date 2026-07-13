"""Authorized corpus-retrieval capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .service import RetrievalService

__all__ = ["RetrievalService"]


def __getattr__(name: str) -> Any:
    if name == "RetrievalService":
        from .service import RetrievalService

        return RetrievalService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
