"""Sparse vector wire contract for Qdrant hybrid retrieval."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]

    def as_qdrant(self) -> dict[str, list[int] | list[float]]:
        return {"indices": self.indices, "values": self.values}
