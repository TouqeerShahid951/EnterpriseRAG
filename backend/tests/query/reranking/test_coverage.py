# ruff: noqa: F403, F405

from reranking_support import *


class RerankHitsTests(unittest.TestCase):
    def test_document_summary_requires_every_selected_unit(self) -> None:
        hits = [
            hit(
                f"section-{index}-child",
                1.0 - index / 100,
                f"section {index} evidence",
                parent_section_id=f"section-{index}",
                parent_chunk_id=f"parent-{index}",
                parent_text=f"section {index} evidence Document Section {index}",
                section_title=f"Document Section {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(5)
        ]
        queries = (
            "Summarize the document",
            "Summarize all repair equipment in the document",
            "Provide a summary of every repair tool in the document",
        )

        for query in queries:
            with (
                self.subTest(query=query),
                patch(
                    "rag.query.reranker._load_cross_encoder",
                    return_value=FakeCrossEncoder([5.0, 4.0, 3.0, 2.0, 1.0]),
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
            self.assertEqual(
                result.evidence_stop_reason,
                "final_evidence_coverage_incomplete",
            )
            self.assertEqual(len(result.required_coverage_obligations), 5)
    def test_document_summary_without_parent_requires_every_child(self) -> None:
        for page in (None, 7):
            hits: list[SearchHit] = []
            for index in range(5):
                payload: dict[str, object] = {
                    "chunk_type": "table_row",
                    "parent_section_id": "table-section",
                    "parent_chunk_id": "table-parent",
                    "section_title": "Equipment Inventory",
                    "exhaustive_scope_origin": "document_class_scope",
                    "authorized_scan_complete": True,
                }
                if page is not None:
                    payload["page"] = page
                hits.append(
                    hit(
                        f"row-{index}",
                        1.0 - index / 100,
                        f"inventory row {index}",
                        **payload,
                    )
                )

            with (
                self.subTest(page=page),
                patch(
                    "rag.query.reranker._load_cross_encoder",
                    return_value=FakeCrossEncoder([5.0, 4.0, 3.0, 2.0, 1.0]),
                ),
            ):
                result = rerank_hits_with_result(
                    "Summarize the document",
                    hits,
                    top_k=1,
                    max_candidates=5,
                    exhaustive=True,
                )

            child_obligations = {
                obligation
                for obligation in result.required_coverage_obligations
                if obligation.startswith("child:")
            }
            self.assertEqual(len(child_obligations), 5)
            self.assertEqual(result.candidate_coverage_status, "complete")
            self.assertEqual(result.evidence_coverage_status, "partial")
            self.assertEqual(
                result.evidence_stop_reason,
                "final_evidence_coverage_incomplete",
            )
    def test_summary_parent_must_contain_every_child(self) -> None:
        hits = [
            hit(
                f"row-{index}",
                1.0 - index / 100,
                f"inventory row {index}",
                page=7,
                chunk_type="table_row",
                parent_section_id="table-section",
                parent_chunk_id="table-parent",
                parent_text="inventory row 0",
                parent_page_start=7,
                parent_page_end=7,
                section_title="Equipment Inventory",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(2)
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
    def test_exclusive_section_without_parent_requires_every_child(self) -> None:
        hits = [
            hit(
                f"row-{index}",
                1.0 - index / 100,
                f"unique inventory row {index}",
                page=7,
                chunk_type="table_row",
                parent_section_id="inventory-section",
                parent_chunk_id="inventory-parent",
                section_title="Equipment Inventory",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(5)
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([5.0, 4.0, 3.0, 2.0, 1.0]),
        ):
            result = rerank_hits_with_result(
                "List all items from Equipment Inventory",
                hits,
                top_k=1,
                max_candidates=5,
                exhaustive=True,
            )

        self.assertEqual(
            sum(
                obligation.startswith("child:")
                for obligation in result.required_coverage_obligations
            ),
            5,
        )
        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(
            result.evidence_stop_reason,
            "final_evidence_coverage_incomplete",
        )
    def test_mixed_toc_and_content_unit_remains_coverage_eligible(self) -> None:
        hits = [
            hit(
                "mixed-toc-child",
                1.0,
                (
                    "Tools for Disassembly and Assembly\n"
                    "54 Fasteners for Assembly 56 Back Cover Remove"
                ),
                page=51,
                parent_page_start=51,
                parent_page_end=51,
                parent_section_id="tools-section",
                parent_chunk_id="mixed-parent",
                parent_text=(
                    "Tools for Disassembly and Assembly\n"
                    "54 Fasteners for Assembly 56 Back Cover Remove\n"
                    + "Index listing "
                    * 20
                ),
                section_title="Tools for Disassembly and Assembly",
                quality_flags=["toc"],
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
            hit(
                "mixed-body-child",
                0.9,
                "Safety Goggles and ESD Safe Mat",
                page=51,
                parent_page_start=51,
                parent_page_end=51,
                parent_section_id="tools-section",
                parent_chunk_id="mixed-parent",
                parent_text=(
                    "Tools for Disassembly and Assembly\nSafety Goggles\nESD Safe Mat"
                ),
                section_title="Tools for Disassembly and Assembly",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            ),
        ]

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=FakeCrossEncoder([1.0, 0.0]),
        ):
            result = rerank_hits_with_result(
                "List all items from Tools for Disassembly and Assembly",
                hits,
                top_k=2,
                max_candidates=2,
                exhaustive=True,
            )

        self.assertEqual(
            {item.point_id for item in result.candidates},
            {"mixed-toc-child", "mixed-body-child"},
        )
        self.assertNotIn(
            "mixed-toc-child",
            {item.point_id for item in result.ranked_hits},
        )
        self.assertIn(
            "unit:doc|section:tools-section|parent:mixed-parent",
            result.required_coverage_obligations,
        )
        self.assertTrue(
            any(
                item.point_id == "mixed-body-child"
                and item.payload.get("coverage_role")
                == "exhaustive_section_representative"
                for item in result.ranked_hits
            )
        )
        self.assertEqual(result.evidence_coverage_status, "complete")
    def test_unresolved_exhaustive_item_scope_cannot_report_complete(self) -> None:
        hits = [
            hit(
                f"generic-{index:02d}",
                1.0 - index / 100,
                f"generic section {index}",
                page=index + 1,
                parent_section_id=f"generic-section-{index}",
                parent_chunk_id=f"generic-parent-{index}",
                parent_text=f"generic parent {index}",
                section_title=f"Generic Section {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(30)
        ]
        hits[-1] = hit(
            "tools-last",
            0.01,
            "Safety Goggles; ESD Safe Mat",
            page=30,
            parent_section_id="tools-section",
            parent_chunk_id="tools-parent",
            parent_text="Tools for Disassembly and Assembly\nSafety Goggles\nESD Safe Mat",
            section_title="Tools for Disassembly and Assembly",
            exhaustive_scope_origin="document_class_scope",
            authorized_scan_complete=True,
        )

        with patch(
            "rag.query.reranker._load_cross_encoder",
            return_value=LowReferencedSectionCrossEncoder(),
        ):
            result = rerank_hits_with_result(
                "List all equipment required to repair the device and do not miss any",
                hits,
                top_k=24,
                max_candidates=24,
                exhaustive=True,
            )

        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(result.evidence_stop_reason, "semantic_scope_unresolved")
        self.assertIn(
            "tools-last",
            {item.point_id for item in result.ranked_hits},
        )
    def test_full_section_query_reserves_every_section_in_one_document(self) -> None:
        hits = [
            hit(
                f"section-{index}-child",
                1.0 - index / 100,
                f"section {index} evidence",
                parent_section_id=f"section-{index}",
                parent_chunk_id=f"parent-{index}",
                parent_text=f"complete section {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for index in range(9)
        ]
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "list every section in the whole document",
                hits,
                top_k=12,
                max_candidates=4,
                exhaustive=True,
            )

        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "complete")
        self.assertEqual(
            {
                item.payload.get("parent_section_id")
                for item in result.ranked_hits
                if item.payload.get("coverage_role")
                == "exhaustive_section_representative"
            },
            {f"section-{index}" for index in range(9)},
        )
    def test_full_document_page_coverage_cannot_report_false_complete(self) -> None:
        hits = [
            hit(
                f"page-{page}",
                1.0 - page / 100,
                f"page {page} evidence",
                page=page,
                parent_section_id="long-section",
                parent_chunk_id="long-parent",
                parent_text="long section " + ("content " * 700),
                parent_page_start=1,
                parent_page_end=30,
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for page in range(1, 31)
        ]
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "list the entire document",
                hits,
                top_k=24,
                max_candidates=40,
                exhaustive=True,
            )

        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(
            result.evidence_stop_reason,
            "final_evidence_coverage_incomplete",
        )
        self.assertEqual(len(result.required_coverage_obligations), 61)
        self.assertEqual(
            sum(
                obligation.startswith("child:")
                for obligation in result.required_coverage_obligations
            ),
            30,
        )
        self.assertLess(
            len(result.covered_coverage_obligations),
            len(result.required_coverage_obligations),
        )
    def test_exhaustive_scan_truncation_cannot_report_complete_coverage(self) -> None:
        hits = [
            hit(
                f"chunk-{index}",
                1.0,
                f"passage {index}",
                parent_chunk_id=f"parent-{index}",
                parent_text=f"parent passage {index}",
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=False,
            )
            for index in range(3)
        ]
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "list everything",
                hits,
                top_k=3,
                max_candidates=40,
                exhaustive=True,
            )

        self.assertEqual(result.candidate_coverage_status, "partial")
        self.assertEqual(result.evidence_coverage_status, "partial")
        self.assertEqual(result.stop_reason, "authorized_scan_truncated")
    def test_exhaustive_final_evidence_reserves_each_scoped_document(self) -> None:
        hits = [
            hit(
                f"doc-{doc_index}-chunk-{child_index}",
                1.0,
                f"document {doc_index} child {child_index}",
                doc_id=f"doc-{doc_index}",
                parent_section_id=f"section-{doc_index}",
                parent_chunk_id=f"parent-{doc_index}",
                parent_text="\n".join(
                    f"document {doc_index} child {item}" for item in range(10)
                ),
                exhaustive_scope_origin="document_class_scope",
                authorized_scan_complete=True,
            )
            for doc_index in range(9)
            for child_index in range(10)
        ]
        model = RecordingCrossEncoder()

        with patch("rag.query.reranker._load_cross_encoder", return_value=model):
            result = rerank_hits_with_result(
                "list everything in every document",
                hits,
                top_k=24,
                max_candidates=40,
                exhaustive=True,
            )

        self.assertEqual(result.candidate_coverage_status, "complete")
        self.assertEqual(result.evidence_coverage_status, "complete")
        self.assertEqual(
            {item.payload["doc_id"] for item in result.ranked_hits},
            {f"doc-{index}" for index in range(9)},
        )
