# ruff: noqa: F403, F405

from reranking_support import *


class RerankHitsTests(unittest.TestCase):
    def test_inverse_or_ambiguous_section_scope_fails_closed(self) -> None:
        hits = [
            hit(
                "tools-child",
                0.9,
                "Safety Goggles and ESD Safe Mat",
                parent_section_id="tools-section",
                parent_chunk_id="tools-parent",
                parent_text="Tools for Disassembly and Assembly",
                section_title="Tools for Disassembly and Assembly",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "accessories-child",
                0.8,
                "Vacuum Pen and Heating Separator",
                parent_section_id="accessories-section",
                parent_chunk_id="accessories-parent",
                parent_text="Workshop Accessories",
                section_title="Workshop Accessories",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]
        queries = (
            "List all repair equipment not in Tools for Disassembly and Assembly",
            "List all repair equipment not inside Tools for Disassembly and Assembly",
            "List all repair equipment not under Tools for Disassembly and Assembly",
            "List all repair equipment not within Tools for Disassembly and Assembly",
            "List all repair equipment except those in Tools for Disassembly and Assembly",
            "Apart from Tools for Disassembly and Assembly list all repair equipment",
            "Aside from Tools for Disassembly and Assembly list all repair equipment",
            "Different from Tools for Disassembly and Assembly list all repair equipment",
            "Do not include equipment found in Tools for Disassembly and Assembly list all others",
            "Without using anything from Tools for Disassembly and Assembly list all repair equipment",
            "Omit items from Tools for Disassembly and Assembly and list all repair equipment",
            "Ignore items from Tools for Disassembly and Assembly and list all repair equipment",
            "Avoid items from Tools for Disassembly and Assembly and list all repair equipment",
            "List all equipment except for items listed in Tools for Disassembly and Assembly",
            "List all repair equipment that isn't in Tools for Disassembly and Assembly",
            "List all repair equipment that aren't in Tools for Disassembly and Assembly",
            "List all repair equipment that wasn't in Tools for Disassembly and Assembly",
            "List equipment that shouldn't come from Tools for Disassembly and Assembly",
            "I need no equipment from Tools for Disassembly and Assembly",
            "Skip items from Tools for Disassembly and Assembly and list all others",
            "Leave out items from Tools for Disassembly and Assembly and list all others",
            "Drop items from Tools for Disassembly and Assembly and list all others",
            "Discard items from Tools for Disassembly and Assembly and list all others",
            "Filter out items from Tools for Disassembly and Assembly and list all others",
            "The information from Tools for Disassembly and Assembly may be incomplete list all repair equipment",
            "An earlier answer copied from Tools for Disassembly and Assembly missed items list all repair equipment",
            "The list is from Tools for Disassembly and Assembly",
            "This equipment list is from Tools for Disassembly and Assembly",
            "I need 0 equipment from Tools for Disassembly and Assembly",
            "If I need equipment from Tools for Disassembly and Assembly",
            "I need equipment or from Tools for Disassembly and Assembly",
            "I need to from Tools for Disassembly and Assembly",
            "I need is equipment from Tools for Disassembly and Assembly",
            "Provide of from Tools for Disassembly and Assembly",
            "List the from Tools for Disassembly and Assembly",
            "I want the evidence is from Tools for Disassembly and Assembly",
            "Which list is from Tools for Disassembly and Assembly",
            "List all items from Tools for Disassembly and Assembly except items from Tools for Disassembly and Assembly",
            "List all items from Tools for Disassembly and Assembly and Tools for Disassembly and Assembly but not Tools for Disassembly and Assembly",
        )

        for query in queries:
            with (
                self.subTest(query=query),
                patch(
                    "rag.query.reranker._load_cross_encoder",
                    return_value=FakeCrossEncoder([2.0, 1.0]),
                ),
            ):
                result = rerank_hits_with_result(
                    query,
                    hits,
                    top_k=2,
                    max_candidates=2,
                    exhaustive=True,
                )

            self.assertEqual(result.candidate_coverage_status, "complete")
            self.assertEqual(result.evidence_coverage_status, "partial")
            self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
    def test_unconsumed_broad_scope_suffix_fails_closed(self) -> None:
        hits = [
            hit(
                "tools-child",
                0.9,
                "Safety Goggles and ESD Safe Mat",
                parent_section_id="tools-section",
                parent_chunk_id="tools-parent",
                parent_text="Tools for Disassembly and Assembly",
                section_title="Tools for Disassembly and Assembly",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "accessories-child",
                0.8,
                "Vacuum Pen and Heating Separator",
                parent_section_id="accessories-section",
                parent_chunk_id="accessories-parent",
                parent_text="Workshop Accessories",
                section_title="Workshop Accessories",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]
        queries = (
            "List all equipment from Tools for Disassembly and Assembly and all other sections",
            "List all equipment from Tools for Disassembly and Assembly without skipping any section",
            "List all equipment from Tools for Disassembly and Assembly and elsewhere in the document",
        )

        for query in queries:
            with (
                self.subTest(query=query),
                patch(
                    "rag.query.reranker._load_cross_encoder",
                    return_value=FakeCrossEncoder([2.0, 1.0]),
                ),
            ):
                result = rerank_hits_with_result(
                    query,
                    hits,
                    top_k=2,
                    max_candidates=2,
                    exhaustive=True,
                )

            self.assertEqual(result.evidence_coverage_status, "partial")
            self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
            self.assertEqual(
                {item.payload.get("parent_section_id") for item in result.ranked_hits},
                {"tools-section", "accessories-section"},
            )
    def test_toc_only_reference_target_fails_closed_semantic_scope(self) -> None:
        hits = [
            hit(
                "toc-tools",
                1.0,
                (
                    "Tools for Disassembly and Assembly\n"
                    "51 Safety Tools 54 Fasteners for Assembly"
                ),
                page=2,
                parent_section_id="tools-section",
                parent_chunk_id="toc-parent",
                parent_text=(
                    "Tools for Disassembly and Assembly\n"
                    "51 Safety Tools 54 Fasteners for Assembly"
                ),
                section_title="Tools for Disassembly and Assembly",
                quality_flags=["toc"],
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "repair-precautions",
                0.9,
                "Before repair, refer to Tools for Disassembly and Assembly.",
                page=4,
                parent_page_start=4,
                parent_page_end=4,
                parent_section_id="precautions-section",
                parent_chunk_id="precautions-parent",
                parent_text=(
                    "Precautions for Repair\n"
                    "Before repair, refer to Tools for Disassembly and Assembly."
                ),
                section_title="Precautions for Repair",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "general-safety",
                0.8,
                "Follow general safety guidance.",
                page=5,
                parent_page_start=5,
                parent_page_end=5,
                parent_section_id="safety-section",
                parent_chunk_id="safety-parent",
                parent_text="General Safety Guidance",
                section_title="General Safety Guidance",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([100.0, 10.0, 0.0]),
        ):
            result = rerank_hits_with_result(
                "List all repair equipment and do not miss any",
                hits,
                top_k=3,
                max_candidates=3,
                exhaustive=True,
            )

        self.assertNotIn(
            "toc-tools",
            {item.point_id for item in result.candidates},
        )
        self.assertNotIn(
            "toc-tools",
            {item.point_id for item in result.ranked_hits},
        )
        self.assertNotIn("page:doc:2", result.required_coverage_obligations)
        self.assertFalse(
            any(
                "parent:toc-parent" in obligation
                for obligation in result.required_coverage_obligations
            )
        )
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
    def test_expired_exhaustive_deadline_does_not_load_the_model(self) -> None:
        hits = [
            hit(
                "chunk",
                1.0,
                "evidence",
                parent_chunk_id="parent",
                parent_text="parent evidence",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
        ]

        with patch("rag.query.reranker._load_cross_encoder") as load_model:
            result = rerank_hits_with_result(
                "list everything",
                hits,
                top_k=1,
                max_candidates=40,
                exhaustive=True,
                deadline=0.0,
            )

        load_model.assert_not_called()
        self.assertEqual(result.candidate_coverage_status, "partial")
        self.assertEqual(result.evidence_coverage_status, "unknown")
        self.assertEqual(result.stop_reason, "deadline_exceeded")
    def test_parent_coverage_stabilizes_before_optional_children_finish(self) -> None:
        parent_text = "\n".join(
            f"item {index} Equipment Inventory" for index in range(40)
        )
        hits = [
            hit(
                f"item-{index}",
                1.0 - index / 100,
                f"item {index}",
                page=1,
                parent_page_start=1,
                parent_page_end=1,
                parent_section_id="inventory-section",
                parent_chunk_id="inventory-parent",
                parent_text=parent_text,
                section_title="Equipment Inventory",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(40)
        ]

        with (
            patch(
                "rag.query.reranker._load_cross_encoder",
                return_value=FakeCrossEncoder([1.0] * 40),
            ),
            patch(
                "rag.query.reranker.monotonic",
                side_effect=[0.0, 0.0, 0.0, 11.0],
            ),
        ):
            result = rerank_hits_with_result(
                "List all items from Equipment Inventory",
                hits,
                top_k=2,
                max_candidates=40,
                exhaustive=True,
                deadline=10.0,
            )

        self.assertEqual(len(result.candidates), 32)
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "complete")
        self.assertIsNone(result.stop_reason)
    def test_exhaustive_reranker_failure_is_unknown_and_bounded(self) -> None:
        hits = [
            hit(
                f"chunk-{index}",
                1.0 - index / 100,
                f"passage {index}",
                parent_chunk_id=f"parent-{index}",
                parent_text=f"parent passage {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(50)
        ]

        with (
            patch(
                "rag.query.reranker._load_cross_encoder",
                side_effect=RuntimeError("model unavailable"),
            ),
            self.assertLogs("rag.query.reranker", level="WARNING"),
        ):
            result = rerank_hits_with_result(
                "list everything",
                hits,
                top_k=10,
                max_candidates=40,
                exhaustive=True,
            )

        self.assertEqual(result.candidate_coverage_status, "unknown")
        self.assertEqual(result.evidence_coverage_status, "unknown")
        self.assertEqual(result.stop_reason, "reranker_error")
        self.assertEqual(len(result.candidates), 40)
        self.assertTrue(
            all(
                item.payload["_rerank_status"] == "fallback"
                for item in result.ranked_hits
            )
        )
    def test_fallback_marks_hits_when_cross_encoder_fails(self) -> None:
        hits = [
            hit("low", 0.20, "general text"),
            hit("strong", 0.95, "alpha policy match"),
        ]

        with (
            patch(
                "rag.query.reranker._load_cross_encoder",
                side_effect=RuntimeError("model unavailable"),
            ),
            self.assertLogs("rag.query.reranker", level="WARNING"),
        ):
            ranked = rerank_hits("alpha policy", hits, top_k=1, max_candidates=2)

        self.assertEqual(ranked[0].point_id, "strong")
        self.assertEqual(ranked[0].payload["_rerank_status"], "fallback")
        self.assertEqual(ranked[0].payload["_rerank_error"], "RuntimeError")
        self.assertEqual(ranked[0].payload["_rerank_candidate_count"], 2)
        self.assertNotIn("_rerank_score", ranked[0].payload)
    def test_fallback_uses_low_value_penalty_as_tie_breaker(self) -> None:
        hits = [
            hit(
                "toc",
                0.50,
                "Alpha policy .......... 4",
                section_title="Table of Contents",
            ),
            hit("body", 0.50, "Alpha policy details include renewal requirements."),
        ]

        with (
            patch(
                "rag.query.reranker._load_cross_encoder",
                side_effect=RuntimeError("model unavailable"),
            ),
            self.assertLogs("rag.query.reranker", level="WARNING"),
        ):
            ranked = rerank_hits("alpha policy", hits, top_k=2)

        self.assertEqual([item.point_id for item in ranked], ["body", "toc"])
        self.assertEqual(ranked[1].payload["_rerank_status"], "fallback")
        self.assertEqual(ranked[1].payload["_low_value_penalty"], 0.35)
        self.assertNotIn("_rerank_score", ranked[1].payload)
        self.assertNotIn("_rerank_adjusted_score", ranked[1].payload)
