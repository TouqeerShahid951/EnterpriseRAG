"""NATO clearance level contracts shared by auth, ingestion, and retrieval."""

from __future__ import annotations

from typing import Literal, TypeAlias

ClearanceLevel: TypeAlias = Literal[
    "NATO_UNCLASSIFIED",
    "NATO_RESTRICTED",
    "NATO_CONFIDENTIAL",
    "NATO_SECRET",
    "COSMIC_TOP_SECRET",
]

CLEARANCE_LEVELS: tuple[ClearanceLevel, ...] = (
    "NATO_UNCLASSIFIED",
    "NATO_RESTRICTED",
    "NATO_CONFIDENTIAL",
    "NATO_SECRET",
    "COSMIC_TOP_SECRET",
)

DEFAULT_CLEARANCE_LEVEL: ClearanceLevel = "NATO_RESTRICTED"
MAX_CLEARANCE_LEVEL: ClearanceLevel = "COSMIC_TOP_SECRET"

_RANKS = {level: index for index, level in enumerate(CLEARANCE_LEVELS)}


def normalize_clearance_level(value: str | None) -> ClearanceLevel:
    candidate = (value or DEFAULT_CLEARANCE_LEVEL).strip().upper()
    if candidate not in _RANKS:
        allowed = ", ".join(CLEARANCE_LEVELS)
        raise ValueError(f"clearance_level must be one of: {allowed}")
    return candidate  # type: ignore[return-value]


def clearance_rank(level: str | None) -> int:
    return _RANKS[normalize_clearance_level(level)]


def can_access_clearance(user_level: str | None, document_level: str | None) -> bool:
    return clearance_rank(document_level) <= clearance_rank(user_level)


def clearance_levels_at_or_below(level: str | None) -> tuple[ClearanceLevel, ...]:
    rank = clearance_rank(level)
    return CLEARANCE_LEVELS[: rank + 1]
