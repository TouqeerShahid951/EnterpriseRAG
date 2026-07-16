# ruff: noqa: F403, F405

from reranking_support import *


class RerankHitsTests(unittest.TestCase):
    def test_exhaustive_coverage_beyond_point_cap_enters_rerank_input(self) -> None:
        target_positions = {65: 51, 75: 52, 196: 53}
        hits: list[SearchHit] = []
        for index in range(236):
            page = target_positions.get(index, index // 4 + 1)
            target = index in target_positions
            hits.append(
                hit(
                    f"chunk-{index:03d}",
                    1.0 - index / 1000,
                    (
                        "repair tool evidence"
                        if target
                        else (
                            "Refer to Tools for Disassembly and Assembly."
                            if index == 0
                            else f"generic passage {index}"
                        )
                    ),
                    page=page,
                    parent_page_start=51 if target else page,
                    parent_page_end=53 if target else page,
                    parent_section_id="tools" if target else f"section-{index}",
                    parent_chunk_id="tools-parent" if target else f"parent-{index}",
                    parent_text=(
                        "Tools for Disassembly and Assembly\n"
                        "complete repair tool inventory across pages 51 through 53"
                        if target
                        else f"generic parent passage {index}"
                    ),
                    section_title=(
                        "Tools for Disassembly and Assembly"
                        if target
                        else f"Generic Section {index}"
                    ),
                    exhaustive_scope_origin="document_class_scope",
                    authorized_scan_complete=True,
                )
            )
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "list every repair tool and do not miss any",
                hits,
                top_k=24,
                max_candidates=40,
                exhaustive=True,
            )

        target_candidates = [
            item
            for item in result.candidates
            if item.payload.get("parent_chunk_id") == "tools-parent"
        ]
        self.assertEqual(
            {item.payload["page"] for item in target_candidates}, {51, 52, 53}
        )
        self.assertTrue(
            any(
                item.payload["page_start"] == 51
                and item.payload["page_end"] == 53
                for item in target_candidates
            )
        )
        self.assertLess(len(result.candidates), len(hits))
        self.assertTrue(
            {"page:doc:51", "page:doc:52", "page:doc:53"}
            <= set(result.required_coverage_obligations)
        )
        self.assertEqual(result.representative_count, 234)
        self.assertEqual(result.representative_scored_count, 234)
        self.assertEqual(result.strategy, "exhaustive_hierarchical")
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
        self.assertTrue(model.calls)
        self.assertTrue(all(len(call) <= 32 for call in model.calls))
        self.assertTrue(
            any(
                item.payload.get("coverage_role") == "exhaustive_section_representative"
                and item.payload.get("parent_chunk_id") == "tools-parent"
                for item in result.ranked_hits
            )
        )
    def test_exhaustive_child_rerank_text_is_compact_and_stratified(self) -> None:
        child_text = (
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
                        child_text,
                        parent_section_id="tools",
                        parent_chunk_id="tools-parent",
                        parent_text="Focused Tools",
                        section_title="Focused Tools",
                        exhaustive_scope_origin="document_class_scope",
                        authorized_scan_complete=True,
                    )
                ],
                top_k=1,
                max_candidates=40,
                exhaustive=True,
            )

        child_passage = model.calls[1][0]
        self.assertLessEqual(len(child_passage), 1024)
        self.assertIn("HEAD_MARKER", child_passage)
        self.assertIn("MIDDLE_MARKER", child_passage)
        self.assertIn("TAIL_MARKER", child_passage)
    def test_exhaustive_selection_is_deterministic_waved_and_duplicate_free(
        self,
    ) -> None:
        hits = [
            hit(
                f"chunk-{index:03d}",
                1.0 - index / 1000,
                f"passage {index}",
                doc_id=f"doc-{index % 3}",
                page=index + 1,
                parent_section_id=f"section-{index}",
                parent_chunk_id=f"parent-{index}",
                parent_text=f"parent passage {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(600)
        ]

        results = []
        models = []
        for _ in range(2):
            model = RecordingCrossEncoder()
            models.append(model)
            with patch("rag.query.reranker._load_cross_encoder", return_value=model):
                results.append(
                    rerank_hits_with_result(
                        "list everything",
                        hits,
                        top_k=24,
                        max_candidates=40,
                        exhaustive=True,
                    )
                )

        candidate_ids = [
            [item.point_id for item in result.candidates] for result in results
        ]
        self.assertEqual(candidate_ids[0], candidate_ids[1])
        self.assertEqual(len(candidate_ids[0]), 600)
        self.assertEqual(len(candidate_ids[0]), len(set(candidate_ids[0])))
        self.assertTrue(
            all(result.candidate_coverage_status == "complete" for result in results)
        )
        self.assertTrue(
            all(result.evidence_coverage_status == "partial" for result in results)
        )
        self.assertTrue(
            all(
                result.evidence_stop_reason == "final_evidence_coverage_incomplete"
                for result in results
            )
        )
        self.assertTrue(all(result.stop_reason is None for result in results))
        self.assertTrue(all(result.candidate_wave_count == 2 for result in results))
        self.assertTrue(
            all(len(call) <= 32 for model in models for call in model.calls)
        )
