# ruff: noqa: F403, F405

from reranking_support import *


class RerankHitsTests(unittest.TestCase):
    def test_result_exposes_exact_post_limiter_cross_encoder_input(self) -> None:
        hits = [
            hit(f"chunk-{index:03d}", 1.0 - index / 1000, f"generic passage {index}")
            for index in range(236)
        ]
        model = FakeCrossEncoder([float(40 - index) for index in range(40)])

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "needle",
                hits,
                top_k=5,
                max_candidates=40,
            )

        self.assertEqual(len(result.candidates), 40)
        self.assertEqual(
            [item.point_id for item in result.candidates],
            [f"chunk-{index:03d}" for index in range(40)],
        )
        self.assertEqual(len(result.ranked_hits), 5)
        self.assertTrue(
            all(
                item.payload["_rerank_candidate_count"] == 40
                for item in result.ranked_hits
            )
        )
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
    def test_table_field_label_promotion_can_still_lift_exact_label_matches(
        self,
    ) -> None:
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
