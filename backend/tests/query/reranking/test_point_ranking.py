# ruff: noqa: F403, F405

from reranking_support import *
from rag.query.reranker import _reranker_execution_providers


class PassageCrossEncoder:
    def __init__(self, winning_text: str) -> None:
        self.winning_text = winning_text
        self.calls: list[list[str]] = []

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append(passages)
        return [1.0 if self.winning_text in passage else 0.0 for passage in passages]


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
        self.assertEqual(len(result.ranked_candidates), 40)
        self.assertTrue(
            all(
                item.payload["_rerank_candidate_count"] == 40
                for item in result.ranked_candidates
            )
        )

    def test_complete_bounded_pool_is_scored_in_bounded_batches(self) -> None:
        query = "What is the reference number of the offer letter for Touqeer?"
        hits = [
            hit(
                "wrong",
                0.99,
                "Offer letter reference number WRONG-999 for Umer.",
                doc_title="Offer Letter.pdf",
                page=1,
                structured_kind="kv_record",
                structured_fields=[
                    {"label": "Reference number", "value": "WRONG-999"},
                    {"label": "Recipient", "value": "Umer"},
                ],
            ),
            *[
                hit(f"chunk-{index:02d}", 0.8 - index / 100, f"generic passage {index}")
                for index in range(1, 40)
            ],
        ]
        hits[30] = hit(
            "correct",
            0.69,
            "Offer letter reference number RIGHT-041 for Touqeer.",
            structured_kind="kv_record",
            structured_fields=[
                {"label": "Reference number", "value": "RIGHT-041"},
                {"label": "Recipient", "value": "Touqeer"},
            ],
        )
        model = PassageCrossEncoder("RIGHT-041")

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                query,
                hits,
                top_k=5,
                max_candidates=40,
            )

        self.assertEqual([len(call) for call in model.calls], [8, 8, 8, 8, 8])
        self.assertIsNone(result.stop_reason)
        self.assertEqual(result.candidate_wave_count, 5)
        self.assertEqual(result.ranked_hits[0].point_id, "correct")

    def test_short_context_passage_keeps_chunk_text_ahead_of_summary(self) -> None:
        model = PassageCrossEncoder("NEEDLE")
        candidate = hit(
            "chunk",
            0.9,
            f"{'x' * 900} NEEDLE",
            doc_title="Record.pdf",
            doc_summary="summary " * 1_000,
        )

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            rerank_hits(
                "find needle",
                [candidate],
                top_k=1,
                model_name="BAAI/bge-reranker-base",
            )

        passage = model.calls[0][0]
        self.assertLessEqual(len(passage), 1_400)
        self.assertIn("NEEDLE", passage)
        self.assertLess(passage.index("NEEDLE"), passage.index("summary"))

    def test_long_context_model_receives_more_chunk_text(self) -> None:
        model = PassageCrossEncoder("NEEDLE")
        candidate = hit("chunk", 0.9, f"NEEDLE {'x' * 5_000}")

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            rerank_hits(
                "find needle",
                [candidate],
                top_k=1,
                model_name="BAAI/bge-reranker-base",
            )
            rerank_hits(
                "find needle",
                [candidate],
                top_k=1,
                model_name="jinaai/jina-reranker-v1-turbo-en",
            )

        self.assertEqual(len(model.calls[0][0]), 1_400)
        self.assertEqual(len(model.calls[1][0]), 4_000)

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

    def test_candidate_limit_reserves_each_available_retrieval_capability(self) -> None:
        hits = [
            hit(
                f"general-{index}",
                1.0 - index / 100,
                f"general passage {index}",
                _retrieval_capabilities=["general_search"],
            )
            for index in range(20)
        ]
        hits.append(
            hit(
                "specialist",
                0.01,
                "specialist answer",
                _retrieval_capabilities=["live_sql"],
            )
        )
        model = PassageCrossEncoder("specialist answer")

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "find answer",
                hits,
                top_k=2,
                max_candidates=10,
            )

        self.assertIn("specialist", [hit.point_id for hit in result.candidates])
        self.assertEqual(result.ranked_hits[0].point_id, "specialist")
        self.assertEqual(
            result.ranked_hits[0].payload["_rerank_status"],
            "scored",
        )

    def test_candidate_limit_reserves_each_available_subquery(self) -> None:
        hits = [
            hit(
                f"first-{index}",
                1.0 - index / 100,
                f"first side {index}",
                _retrieval_query_slots=[0],
            )
            for index in range(20)
        ]
        hits.append(
            hit(
                "second-side",
                0.01,
                "second side answer",
                _retrieval_query_slots=[1],
            )
        )
        model = PassageCrossEncoder("second side answer")

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "compare both sides",
                hits,
                top_k=2,
                max_candidates=10,
            )

        self.assertIn("second-side", [item.point_id for item in result.candidates])
        self.assertEqual(result.ranked_hits[0].point_id, "second-side")

    def test_expired_deadline_returns_explicit_retrieval_fallback(self) -> None:
        model = PassageCrossEncoder("unused")

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "alpha",
                [hit("first", 1.0, "alpha"), hit("second", 0.5, "beta")],
                top_k=2,
                max_candidates=2,
                deadline=0,
            )

        self.assertEqual(result.stop_reason, "deadline_exceeded")
        self.assertEqual(result.candidate_wave_count, 0)
        self.assertEqual(model.calls, [])
        self.assertTrue(
            all(
                item.payload["_rerank_status"] == "fallback"
                for item in result.ranked_hits
            )
        )

    def test_reranker_score_stays_primary_over_exact_field_label_match(
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

        self.assertEqual([item.point_id for item in ranked], ["generic", "table"])
        self.assertEqual(ranked[0].payload["_rerank_score"], 0.99)
        self.assertEqual(ranked[0].payload["_rerank_status"], "scored")
        self.assertEqual(ranked[0].payload["_low_value_penalty"], 0.0)


class RerankerDeviceTests(unittest.TestCase):
    def test_cpu_device_never_selects_cuda(self) -> None:
        self.assertEqual(
            _reranker_execution_providers(
                "cpu", ["CUDAExecutionProvider", "CPUExecutionProvider"]
            ),
            ("CPUExecutionProvider",),
        )

    def test_auto_prefers_cuda_with_cpu_operator_fallback(self) -> None:
        self.assertEqual(
            _reranker_execution_providers(
                "auto", ["CUDAExecutionProvider", "CPUExecutionProvider"]
            ),
            ("CUDAExecutionProvider", "CPUExecutionProvider"),
        )

    def test_explicit_cuda_fails_when_gpu_runtime_is_missing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "CUDAExecutionProvider is unavailable"):
            _reranker_execution_providers("cuda", ["CPUExecutionProvider"])
