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
        self.assertEqual(ranked[0].payload["_low_value_penalty"], 0.0)

    def test_low_value_toc_chunk_is_soft_downranked_after_reranking(self) -> None:
        hits = [
            hit(
                "toc",
                0.90,
                "Table of Contents\nWarranty claim process .......... 12\nWarranty exceptions .......... 13",
                section_title="Table of Contents",
            ),
            hit("body", 0.50, "Warranty claims require proof of purchase and manager approval."),
        ]
        model = FakeCrossEncoder([0.92, 0.70])

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            ranked = rerank_hits("what is the warranty claim process", hits, top_k=2)

        self.assertEqual([item.point_id for item in ranked], ["body", "toc"])
        toc = ranked[1]
        self.assertEqual(toc.payload["_rerank_score"], 0.92)
        self.assertEqual(toc.payload["_low_value_penalty"], 0.35)
        self.assertEqual(toc.payload["_rerank_adjusted_score"], 0.57)
        self.assertIn("toc_or_index", toc.payload["_low_value_reasons"])

    def test_explicit_toc_query_does_not_downrank_toc_chunk(self) -> None:
        hits = [
            hit(
                "toc",
                0.90,
                "Table of Contents\nWarranty claim process .......... 12\nWarranty exceptions .......... 13",
                section_title="Table of Contents",
            ),
            hit("body", 0.50, "Warranty claims require proof of purchase and manager approval."),
        ]
        model = FakeCrossEncoder([0.80, 0.70])

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            ranked = rerank_hits("show the table of contents", hits, top_k=2)

        self.assertEqual([item.point_id for item in ranked], ["toc", "body"])
        self.assertEqual(ranked[0].payload["_rerank_score"], 0.80)
        self.assertEqual(ranked[0].payload["_low_value_penalty"], 0.0)
        self.assertEqual(ranked[0].payload["_rerank_adjusted_score"], 0.80)

    def test_fallback_uses_low_value_penalty_as_tie_breaker(self) -> None:
        hits = [
            hit("toc", 0.50, "Alpha policy .......... 4", section_title="Contents"),
            hit("body", 0.50, "Alpha policy details include renewal requirements."),
        ]

        with (
            patch("rag.query.reranker._load_cross_encoder", side_effect=RuntimeError("model unavailable")),
            self.assertLogs("rag.query.reranker", level="WARNING"),
        ):
            ranked = rerank_hits("alpha policy", hits, top_k=2)

        self.assertEqual([item.point_id for item in ranked], ["body", "toc"])
        self.assertEqual(ranked[1].payload["_rerank_status"], "fallback")
        self.assertEqual(ranked[1].payload["_low_value_penalty"], 0.35)
        self.assertNotIn("_rerank_score", ranked[1].payload)
        self.assertNotIn("_rerank_adjusted_score", ranked[1].payload)


if __name__ == "__main__":
    unittest.main()
