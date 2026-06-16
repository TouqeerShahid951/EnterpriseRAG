from __future__ import annotations

import unittest
from unittest.mock import patch

from rag.query.qdrant import SearchHit
from rag.query.reranker import rerank_hits


class FakeCrossEncoder:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        return self.scores[: len(passages)]


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


class RerankHitsTests(unittest.TestCase):
    def test_candidate_limit_keeps_retrieval_head_without_token_overlap(self) -> None:
        hits = [
            hit("semantic", 0.99, "benefit eligibility depends on tenure"),
            hit("lexical", 0.20, "alpha policy query term"),
            hit("extra", 0.10, "alpha details"),
        ]
        model = FakeCrossEncoder([0.95, 0.10])

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            ranked = rerank_hits("alpha policy", hits, top_k=2, max_candidates=2)

        self.assertEqual([item.point_id for item in ranked], ["semantic", "lexical"])
        self.assertEqual(ranked[0].payload["_rerank_status"], "scored")
        self.assertEqual(ranked[0].payload["_rerank_candidate_count"], 2)

    def test_fallback_marks_hits_when_cross_encoder_fails(self) -> None:
        hits = [
            hit("low", 0.20, "general text"),
            hit("strong", 0.95, "alpha policy match"),
        ]

        with (
            patch("rag.query.reranker._load_cross_encoder", side_effect=RuntimeError("model unavailable")),
            self.assertLogs("rag.query.reranker", level="WARNING"),
        ):
            ranked = rerank_hits("alpha policy", hits, top_k=1, max_candidates=2)

        self.assertEqual(ranked[0].point_id, "strong")
        self.assertEqual(ranked[0].payload["_rerank_status"], "fallback")
        self.assertEqual(ranked[0].payload["_rerank_error"], "RuntimeError")
        self.assertEqual(ranked[0].payload["_rerank_candidate_count"], 2)
        self.assertNotIn("_rerank_score", ranked[0].payload)

    def test_table_field_label_promotion_can_still_lift_exact_label_matches(self) -> None:
        hits = [
            hit("generic", 0.90, "implementation notes"),
            hit(
                "table",
                0.50,
                "Maximum Limit: 500",
                structured_fields=[{"label": "Maximum Limit", "value": "500"}],
            ),
        ]
        model = FakeCrossEncoder([0.99, 0.10])

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            ranked = rerank_hits("what is the maximum limit", hits, top_k=2)

        self.assertEqual(ranked[0].point_id, "table")
        self.assertEqual(ranked[0].payload["_rerank_score"], 0.10)
        self.assertEqual(ranked[0].payload["_rerank_status"], "scored")


if __name__ == "__main__":
    unittest.main()
