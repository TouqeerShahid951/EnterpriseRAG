from __future__ import annotations

# ruff: noqa: F401

import unittest

from unittest.mock import patch

from rag.query.qdrant import SearchHit

from rag.query.reranker import rerank_hits, rerank_hits_with_result

class FakeCrossEncoder:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        return self.scores[: len(passages)]

class RecordingCrossEncoder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append(passages)
        return [
            100.0 if "complete repair tool inventory" in passage else 0.0
            for passage in passages
        ]

class LowReferencedSectionCrossEncoder:
    def rerank(self, query: str, passages: list[str]) -> list[float]:
        return [
            -100.0
            if "Tools for Disassembly and Assembly" in passage
            else float(100 - index)
            for index, passage in enumerate(passages)
        ]

class BroadEquipmentCrossEncoder:
    def rerank(self, query: str, passages: list[str]) -> list[float]:
        scores: list[float] = []
        for index, passage in enumerate(passages):
            if "Workshop Accessories" in passage:
                scores.append(-300.0)
            elif "Special Repair Equipment" in passage:
                scores.append(-200.0)
            elif "Tools for Disassembly and Assembly" in passage:
                scores.append(-100.0)
            else:
                scores.append(float(100 - index))
        return scores

def hit(point_id: str, score: float, text: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=score,
        payload={
            "doc_id": payload.pop("doc_id", "doc"),
            "chunk_id": point_id,
            "text": text,
            **payload,
        },
    )

if __name__ == "__main__":
    unittest.main()

__all__ = [name for name in globals() if not name.startswith("__")]
