# ruff: noqa: F403, F405

from reranking_support import *


class RerankHitsTests(unittest.TestCase):
    def test_exhaustive_section_representative_is_compact_and_stratified(self) -> None:
        parent_text = (
            "HEAD_MARKER "
            + ("a" * 1800)
            + " MIDDLE_MARKER "
            + ("b" * 1800)
            + " TAIL_MARKER"
        )
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            rerank_hits_with_result(
                "list every repair tool",
                [
                    hit(
                        "tool-child",
                        1.0,
                        "tool evidence",
                        parent_section_id="tools",
                        parent_chunk_id="tools-parent",
                        parent_text=parent_text,
                        section_title="Focused Tools",
                        exhaustive_scope_origin="document_class_scope",
                        authorized_scan_complete=True,
                    )
                ],
                top_k=1,
                max_candidates=40,
                exhaustive=True,
            )

        representative = model.calls[0][0]
        self.assertLessEqual(len(representative), 1024)
        self.assertIn("Focused Tools", representative)
        self.assertIn("HEAD_MARKER", representative)
        self.assertIn("MIDDLE_MARKER", representative)
        self.assertIn("TAIL_MARKER", representative)
    def test_exhaustive_section_larger_than_one_wave_is_not_dropped(self) -> None:
        hits = [
            hit(
                f"large-{index:03d}",
                1.0 - index / 1000,
                f"large section child {index}",
                parent_section_id="large-section",
                parent_chunk_id="large-parent",
                parent_text="large section representative",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(513)
        ]
        hits.append(
            hit(
                "small-000",
                0.1,
                "small section child",
                parent_section_id="small-section",
                parent_chunk_id="small-parent",
                parent_text="small section representative",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
        )
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "list every section",
                hits,
                top_k=8,
                max_candidates=40,
                exhaustive=True,
            )

        self.assertEqual(len(result.candidates), 514)
        self.assertEqual(
            sum(
                item.payload.get("parent_section_id") == "large-section"
                for item in result.candidates
            ),
            513,
        )
        self.assertEqual(result.candidate_wave_count, 2)
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(
            result.evidence_stop_reason,
            "final_evidence_coverage_incomplete",
        )
    def test_named_section_is_protected_even_when_model_scores_it_last(self) -> None:
        hits = [
            hit(
                f"generic-{index:02d}",
                1.0 - index / 100,
                f"generic section {index}",
                parent_section_id=f"generic-section-{index}",
                parent_chunk_id=f"generic-parent-{index}",
                parent_text=f"generic parent {index}",
                section_title=f"Generic Section {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(12)
        ]
        hits.append(
            hit(
                "tools-child",
                0.01,
                "Safety Goggles; ESD Safe Mat",
                parent_section_id="tools-section",
                parent_chunk_id="tools-parent",
                parent_text=(
                    "Tools for Disassembly and Assembly\nSafety Goggles\nESD Safe Mat"
                ),
                section_title="Tools for Disassembly and Assembly",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
        )
        hits.append(
            hit(
                "special-child",
                0.001,
                "Vacuum Pen and Heating Separator",
                parent_section_id="special-section",
                parent_chunk_id="special-parent",
                parent_text="Special Repair Equipment",
                section_title="Special Repair Equipment",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
        )

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=LowReferencedSectionCrossEncoder(),
        ):
            result = rerank_hits_with_result(
                "List all items from Tools for Disassembly and Assembly and do not skip or miss any",
                hits,
                top_k=4,
                max_candidates=4,
                exhaustive=True,
            )

        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "complete")
        self.assertTrue(
            any(
                item.payload.get("parent_section_id") == "tools-section"
                and item.payload.get("coverage_role")
                == "exhaustive_section_representative"
                for item in result.ranked_hits
            )
        )
        self.assertEqual(
            {item.payload.get("parent_section_id") for item in result.ranked_hits},
            {"tools-section"},
        )
    def test_coordinated_explicit_sections_share_scope_preposition(self) -> None:
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
                "special-child",
                0.8,
                "Vacuum Pen and Heating Separator",
                parent_section_id="special-section",
                parent_chunk_id="special-parent",
                parent_text="Special Repair Equipment",
                section_title="Special Repair Equipment",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "general-child",
                0.7,
                "General repair guidance",
                parent_section_id="general-section",
                parent_chunk_id="general-parent",
                parent_text="General Repair Guidance",
                section_title="General Repair Guidance",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([3.0, 2.0, 1.0]),
        ):
            result = rerank_hits_with_result(
                "List all items from Tools for Disassembly and Assembly and Special Repair Equipment",
                hits,
                top_k=3,
                max_candidates=3,
                exhaustive=True,
            )

        self.assertEqual(result.evidence_coverage_status, "complete")
        self.assertEqual(
            {item.payload.get("parent_section_id") for item in result.ranked_hits},
            {"tools-section", "special-section"},
        )
    def test_document_wide_language_vetoes_section_narrowing(self) -> None:
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
            "List all equipment from Tools for Disassembly and Assembly across all sections",
            "List all equipment in Tools for Disassembly and Assembly and every section",
            "List all equipment from Tools for Disassembly and Assembly throughout the document",
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

            self.assertEqual(result.evidence_coverage_status, "complete")
            self.assertEqual(
                {item.payload.get("parent_section_id") for item in result.ranked_hits},
                {"tools-section", "accessories-section"},
            )
    def test_overlapping_heading_mentions_cannot_narrow_scope(self) -> None:
        hits = [
            hit(
                "tools-child",
                0.9,
                "Safety Goggles",
                parent_section_id="tools-section",
                parent_chunk_id="tools-parent",
                parent_text="Tools for Assembly",
                section_title="Tools for Assembly",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "overview-child",
                0.8,
                "Assembly planning guidance",
                parent_section_id="overview-section",
                parent_chunk_id="overview-parent",
                parent_text="Assembly Overview",
                section_title="Assembly Overview",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([2.0, 1.0]),
        ):
            result = rerank_hits_with_result(
                "List all items from Tools for Assembly Overview",
                hits,
                top_k=2,
                max_candidates=2,
                exhaustive=True,
            )

        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
    def test_negated_document_summary_does_not_resolve_scope(self) -> None:
        hits = [
            hit(
                "tools-child",
                0.9,
                "Safety Goggles",
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
                "Vacuum Pen",
                parent_section_id="accessories-section",
                parent_chunk_id="accessories-parent",
                parent_text="Workshop Accessories",
                section_title="Workshop Accessories",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]
        queries = (
            "Do not summarize the document list all repair equipment",
            "I am not asking for a summary of the document list every repair tool",
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
    def test_parent_child_containment_uses_token_boundaries(self) -> None:
        hits = [
            hit(
                "short-child",
                0.9,
                "ESD Mat",
                parent_section_id="equipment-section",
                parent_chunk_id="equipment-parent",
                parent_text="ESD Material",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "long-child",
                0.8,
                "ESD Material",
                parent_section_id="equipment-section",
                parent_chunk_id="equipment-parent",
                parent_text="ESD Material",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([2.0, 1.0]),
        ):
            result = rerank_hits_with_result(
                "Summarize the document",
                hits,
                top_k=1,
                max_candidates=2,
                exhaustive=True,
            )

        self.assertEqual(
            sum(
                obligation.startswith("child:")
                for obligation in result.required_coverage_obligations
            ),
            2,
        )
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(
            result.evidence_stop_reason,
            "final_evidence_coverage_incomplete",
        )
    def test_broad_exhaustive_category_protects_every_matching_heading(self) -> None:
        hits = [
            hit(
                "overview-child",
                1.0,
                "Refer to Tools for Disassembly and Assembly.",
                parent_section_id="overview-section",
                parent_chunk_id="overview-parent",
                parent_text="Refer to Tools for Disassembly and Assembly.",
                section_title="Overview and Introduction",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
        ]
        hits.extend(
            hit(
                f"generic-{index:02d}",
                0.9 - index / 100,
                f"generic section {index}",
                parent_section_id=f"generic-section-{index}",
                parent_chunk_id=f"generic-parent-{index}",
                parent_text=f"generic parent {index}",
                section_title=f"Generic Section {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(45)
        )
        hits.extend(
            [
                hit(
                    "tools-child",
                    0.02,
                    "Safety Goggles and ESD Safe Mat",
                    parent_section_id="tools-section",
                    parent_chunk_id="tools-parent",
                    parent_text="Tools for Disassembly and Assembly",
                    section_title="Tools for Disassembly and Assembly",
                    exhaustive_scope_origin="document_class_scope",
                    authorized_scan_complete=True,
                ),
                hit(
                    "special-child",
                    0.01,
                    "Vacuum Pen and Heating Separator",
                    parent_section_id="special-section",
                    parent_chunk_id="special-parent",
                    parent_text="Special Repair Equipment",
                    section_title="Special Repair Equipment",
                    exhaustive_scope_origin="document_class_scope",
                    authorized_scan_complete=True,
                ),
            ]
        )

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=BroadEquipmentCrossEncoder(),
        ):
            result = rerank_hits_with_result(
                "List all repair equipment and do not miss any",
                hits,
                top_k=24,
                max_candidates=40,
                exhaustive=True,
            )

        ranked_sections = {
            item.payload.get("parent_section_id") for item in result.ranked_hits
        }
        self.assertIn("tools-section", ranked_sections)
        self.assertIn("special-section", ranked_sections)
        self.assertTrue(
            any(
                "special-section" in item
                for item in result.required_coverage_obligations
            )
        )
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
    def test_common_category_headings_cannot_be_silently_filtered(self) -> None:
        hits = [
            hit(
                "overview-child",
                1.0,
                "Refer to Special Tools 0.",
                parent_section_id="overview-section",
                parent_chunk_id="overview-parent",
                parent_text="Refer to Special Tools 0.",
                section_title="Overview and Introduction",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
        ]
        hits.extend(
            hit(
                f"special-{index}",
                0.5 - index / 100,
                f"special tool evidence {index}",
                parent_section_id=f"special-tools-{index}",
                parent_chunk_id=f"special-parent-{index}",
                parent_text=f"Special Tools {index}",
                section_title=f"Special Tools {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(5)
        )
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "List all tools and do not miss any",
                hits,
                top_k=4,
                max_candidates=4,
                exhaustive=True,
            )

        required_special_units = {
            obligation
            for obligation in result.required_coverage_obligations
            if "special-tools-" in obligation
        }
        self.assertEqual(len(required_special_units), 5)
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(
            result.evidence_stop_reason,
            "semantic_scope_unresolved",
        )
    def test_broadening_heading_mention_does_not_resolve_scope(self) -> None:
        hits = [
            hit(
                f"generic-{index:02d}",
                1.0 - index / 100,
                f"generic section {index}",
                parent_section_id=f"generic-section-{index}",
                parent_chunk_id=f"generic-parent-{index}",
                parent_text=f"generic parent {index}",
                section_title=f"Generic Section {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(12)
        ]
        hits.extend(
            [
                hit(
                    "tools-child",
                    0.02,
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
                    0.01,
                    "Vacuum Pen and Heating Separator",
                    parent_section_id="accessories-section",
                    parent_chunk_id="accessories-parent",
                    parent_text="Workshop Accessories",
                    section_title="Workshop Accessories",
                    exhaustive_scope_origin="document_class_scope",
                    authorized_scan_complete=True,
                ),
            ]
        )

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=BroadEquipmentCrossEncoder(),
        ):
            result = rerank_hits_with_result(
                "List all repair equipment, not just Tools for Disassembly and Assembly",
                hits,
                top_k=4,
                max_candidates=4,
                exhaustive=True,
            )

        self.assertNotIn(
            "accessories-section",
            {item.payload.get("parent_section_id") for item in result.ranked_hits},
        )
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
