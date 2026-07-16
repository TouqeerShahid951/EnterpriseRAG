# ruff: noqa: F403, F405

from reranking_support import *


class RerankHitsTests(unittest.TestCase):
    def test_supported_positive_scope_command_families_are_exclusive(self) -> None:
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
                "general-child",
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
        queries = (
            "Show me all items from Tools for Disassembly and Assembly",
            "Provide me all items from Tools for Disassembly and Assembly",
            "Give me a list of all items from Tools for Disassembly and Assembly",
            "Can you give me all items from Tools for Disassembly and Assembly",
            "Extract every record under the section Tools for Disassembly and Assembly",
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
                {"tools-section"},
            )
