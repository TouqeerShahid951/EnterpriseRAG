# ruff: noqa: F403, F405

from reranking_support import *


class RerankHitsTests(unittest.TestCase):
    def test_ambiguous_or_numbered_sections_are_not_removed_as_toc(self) -> None:
        hits = [
            hit(
                "contents-child",
                0.9,
                "2 Batteries\n4 Screws\n1 Charger",
                parent_section_id="contents-section",
                parent_chunk_id="contents-parent",
                parent_text="2 Batteries 4 Screws 1 Charger Contents",
                section_title="Contents",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "index-child",
                0.85,
                "S&P 500 increased twelve percent",
                parent_section_id="index-section",
                parent_chunk_id="index-parent",
                parent_text="S P 500 increased twelve percent Index",
                section_title="Index",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "equipment-child",
                0.82,
                "1 Hammer\n2 Screwdriver\n3 Pliers",
                page=1,
                parent_page_start=1,
                parent_page_end=1,
                parent_section_id="equipment-section",
                parent_chunk_id="equipment-parent",
                parent_text="1 Hammer 2 Screwdriver 3 Pliers Equipment List",
                section_title="Equipment List",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "safety-child",
                0.8,
                "Safety Gloves",
                parent_section_id="safety-section",
                parent_chunk_id="safety-parent",
                parent_text="Safety Gloves Safety Equipment",
                section_title="Safety Equipment",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([4.0, 3.0, 2.0, 1.0]),
        ):
            result = rerank_hits_with_result(
                "Summarize the document",
                hits,
                top_k=4,
                max_candidates=4,
                exhaustive=True,
            )

        self.assertEqual(result.evidence_coverage_status, "complete")
        self.assertEqual(
            {item.payload.get("parent_section_id") for item in result.ranked_hits},
            {
                "contents-section",
                "equipment-section",
                "index-section",
                "safety-section",
            },
        )
    def test_polite_direct_toc_scope_is_still_exclusive(self) -> None:
        hits = [
            hit(
                "toc-child",
                0.9,
                "Table of Contents 2 Introduction 4 Safety Guidance",
                parent_section_id="toc-section",
                parent_chunk_id="toc-parent",
                parent_text="Table of Contents 2 Introduction 4 Safety Guidance",
                section_title="Table of Contents",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "body-child",
                0.8,
                "General repair guidance",
                parent_section_id="general-section",
                parent_chunk_id="general-parent",
                parent_text="General Repair Guidance",
                section_title="General Repair Guidance",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        for query in (
            "Please show the table of contents",
            "Show the table of contents please",
        ):
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

            self.assertEqual(result.evidence_coverage_status, "complete")
            self.assertEqual(
                {item.payload.get("parent_section_id") for item in result.ranked_hits},
                {"toc-section"},
            )
    def test_toc_only_duplicate_heading_unit_is_scored_but_not_forced(self) -> None:
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
                "tools-body",
                0.9,
                "Safety Goggles and ESD Safe Mat",
                page=51,
                parent_page_start=51,
                parent_page_end=51,
                parent_section_id="tools-section",
                parent_chunk_id="tools-parent",
                parent_text=(
                    "Tools for Disassembly and Assembly\n"
                    "complete repair tool inventory\n"
                    "Safety Goggles\nESD Safe Mat"
                ),
                section_title="Tools for Disassembly and Assembly",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "general-body",
                0.8,
                "General repair guidance",
                page=1,
                parent_page_start=1,
                parent_page_end=1,
                parent_section_id="general-section",
                parent_chunk_id="general-parent",
                parent_text="General repair guidance",
                section_title="General Repair Guidance",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([100.0, 10.0, 0.0]),
        ):
            result = rerank_hits_with_result(
                "List all items from Tools for Disassembly and Assembly",
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
        self.assertIn(
            "unit:doc|section:tools-section|parent:tools-parent",
            result.required_coverage_obligations,
        )
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "complete")
    def test_explicit_toc_query_keeps_exhaustive_toc_evidence(self) -> None:
        hits = [
            hit(
                "toc-index",
                1.0,
                "Table of Contents\n2 Introduction 4 Safety Guidance",
                page=1,
                parent_page_start=1,
                parent_page_end=1,
                parent_section_id="toc-section",
                parent_chunk_id="toc-parent",
                parent_text="Table of Contents\n2 Introduction 4 Safety Guidance",
                section_title="Table of Contents",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([1.0]),
        ):
            result = rerank_hits_with_result(
                "Show the table of contents",
                hits,
                top_k=1,
                max_candidates=1,
                exhaustive=True,
            )

        self.assertEqual(
            [item.point_id for item in result.candidates],
            ["toc-index"],
        )
        self.assertEqual(
            [item.point_id for item in result.ranked_hits],
            ["toc-index"],
        )
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "complete")
    def test_table_of_contents_does_not_resolve_semantic_scope(self) -> None:
        hits = [
            hit(
                "toc",
                1.0,
                "Table of Contents\nTools for Disassembly and Assembly ........ 51",
                page=2,
                parent_section_id="toc",
                parent_chunk_id="toc-parent",
                section_title="Table of Contents",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "tools",
                0.9,
                "Safety Goggles",
                page=51,
                parent_section_id="tools",
                parent_chunk_id="tools-parent",
                parent_text="Tools for Disassembly and Assembly\nSafety Goggles",
                section_title="Tools for Disassembly and Assembly",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "list all repair equipment",
                hits,
                top_k=2,
                max_candidates=2,
                exhaustive=True,
            )

        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
    def test_low_value_penalty_does_not_override_reranker_score(self) -> None:
        hits = [
            hit(
                "toc",
                0.90,
                "Table of Contents\nWarranty claim process .......... 12\nWarranty exceptions .......... 13",
                section_title="Table of Contents",
            ),
            hit(
                "body",
                0.50,
                "Warranty claims require proof of purchase and manager approval.",
            ),
        ]
        model = FakeCrossEncoder([0.92, 0.70])

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            ranked = rerank_hits("what is the warranty claim process", hits, top_k=2)

        self.assertEqual([item.point_id for item in ranked], ["toc", "body"])
        toc = ranked[0]
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
            hit(
                "body",
                0.50,
                "Warranty claims require proof of purchase and manager approval.",
            ),
        ]
        model = FakeCrossEncoder([0.80, 0.70])

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            ranked = rerank_hits("show the table of contents", hits, top_k=2)

        self.assertEqual([item.point_id for item in ranked], ["toc", "body"])
        self.assertEqual(ranked[0].payload["_rerank_score"], 0.80)
        self.assertEqual(ranked[0].payload["_low_value_penalty"], 0.0)
        self.assertEqual(ranked[0].payload["_rerank_adjusted_score"], 0.80)
