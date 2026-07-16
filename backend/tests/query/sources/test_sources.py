from __future__ import annotations

import unittest

from rag.query.qdrant import SearchHit
from rag.query.sources import (
    PARENT_PROMOTION_MAX_CHARS,
    SourceAnchor,
    build_evidence_hits,
    parse_citation_tokens,
    source_citation,
)


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


class CitationTests(unittest.TestCase):
    def test_formatter_and_parser_round_trip_supported_chunk_ids(self) -> None:
        sources = [
            SourceAnchor(
                doc_id="doc-a",
                doc_title="Document A",
                chunk_id="doc-a:12",
                excerpt="Numeric chunk",
                group_path="/test",
            ),
            SourceAnchor(
                doc_id="doc-b",
                doc_title="Document B",
                chunk_id="row-alpha",
                excerpt="Named row",
                group_path="/test",
            ),
            SourceAnchor(
                doc_id="doc-c",
                doc_title="Document C",
                chunk_id="section:tools:item-a",
                excerpt="Nested identifier",
                group_path="/test",
            ),
        ]
        labels = tuple(source_citation(source) for source in sources)

        parsed = parse_citation_tokens(
            f"First {labels[0]}, then {labels[1]}, {labels[2]}, and again {labels[1]}."
        )

        self.assertEqual(parsed, (*labels, labels[1]))

    def test_parser_ignores_noncitation_brackets_and_newlines(self) -> None:
        self.assertEqual(
            parse_citation_tokens("[plain] [doc:\nchunk] [doc:chunk]"),
            ("[doc:chunk]",),
        )


class EvidenceBuilderTests(unittest.TestCase):
    def test_exact_chunks_do_not_promote_parent_text_by_default(self) -> None:
        evidence = build_evidence_hits(
            [
                hit(
                    "contact-row",
                    0.80,
                    "Value: Contact Numbers: 03009876543",
                    parent_text="Parent table with unrelated rows.",
                    parent_page_start=1,
                )
            ],
            token_budget=4000,
            limit=1,
        )

        self.assertEqual(
            evidence[0].payload["text"], "Value: Contact Numbers: 03009876543"
        )

    def test_parent_context_is_promoted_when_route_requests_broader_context(
        self,
    ) -> None:
        parent_text = (
            "| Person Information | Case Information |\n"
            "| --- | --- |\n"
            "| Name(s): Sajjad Hussain | Case Type: FIR |\n"
            "| CNIC: 3520212-6789012-7 | Contact Numbers: 03009876543 |"
        )
        hits = [
            hit(
                "contact-row",
                0.80,
                "[Columns: Person Information | Case Information]\n"
                "Row: CNIC: 3520212-6789012-7\n"
                "Value: Contact Numbers: 03009876543",
                chunk_type="table_row",
                parent_chunk_id="table-1",
                parent_text=parent_text,
                parent_page_start=1,
                table_row_index=1,
                structured_kind="table_row",
                structured_fields=[
                    {"label": "Person Information", "value": "CNIC: 3520212-6789012-7"},
                    {
                        "label": "Case Information",
                        "value": "Contact Numbers: 03009876543",
                    },
                ],
            ),
            hit(
                "other-row",
                0.70,
                "[Columns: Person Information | Case Information]\n"
                "Row: Address: Lahore\n"
                "Value: Status: Open",
                chunk_type="table_row",
                parent_chunk_id="table-1",
                parent_text=parent_text,
                parent_page_start=1,
                table_row_index=2,
                structured_kind="table_row",
            ),
        ]

        evidence = build_evidence_hits(
            hits, token_budget=4000, limit=1, broader_table_context=True
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].payload["chunk_id"], "contact-row")
        self.assertIn("Name(s): Sajjad Hussain", evidence[0].payload["text"])
        self.assertIn("Contact Numbers: 03009876543", evidence[0].payload["text"])

    def test_parent_promotion_keeps_the_duplicate_with_complete_obligations(
        self,
    ) -> None:
        parent_text = "Tools for Disassembly and Assembly\nSafety Goggles\nHeating Bag"
        obligations = [
            "unit:doc|section:tools|parent:tools-parent",
            "page:doc:51",
            "page:doc:52",
            "page:doc:53",
        ]
        hits = [
            hit(
                "ranked-first",
                1.0,
                "Safety Goggles",
                parent_chunk_id="tools-parent",
                parent_text=parent_text,
                parent_page_start=51,
                parent_page_end=53,
            ),
            hit(
                "coverage-carrier",
                0.9,
                "Heating Bag",
                parent_chunk_id="tools-parent",
                parent_text=parent_text,
                parent_page_start=51,
                parent_page_end=53,
                coverage_role="exhaustive_section_representative",
                exhaustive_coverage_unit_id="doc|section:tools|parent:tools-parent",
                exhaustive_coverage_obligation_ids=obligations,
            ),
        ]

        evidence = build_evidence_hits(
            hits,
            token_budget=4000,
            limit=1,
            broader_table_context=True,
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].payload["chunk_id"], "coverage-carrier")
        self.assertEqual(
            set(evidence[0].payload["exhaustive_coverage_obligation_ids"]),
            set(obligations),
        )

    def test_promoted_parent_context_is_bounded_around_child_text(self) -> None:
        parent_text = (
            "Intro "
            + ("irrelevant before " * 300)
            + "Contact Numbers: 03009876543 "
            + ("irrelevant after " * 300)
        )

        evidence = build_evidence_hits(
            [
                hit(
                    "contact-row",
                    0.80,
                    "Value: Contact Numbers: 03009876543",
                    parent_text=parent_text,
                    parent_page_start=1,
                )
            ],
            token_budget=4000,
            limit=1,
            broader_table_context=True,
        )

        self.assertLessEqual(
            len(evidence[0].payload["text"]), PARENT_PROMOTION_MAX_CHARS
        )
        self.assertIn("Contact Numbers: 03009876543", evidence[0].payload["text"])

    def test_promoted_parent_context_can_anchor_short_child_values(self) -> None:
        parent_text = (
            "Intro "
            + ("irrelevant before " * 300)
            + "Target answer "
            + ("irrelevant after " * 300)
        )

        evidence = build_evidence_hits(
            [
                hit(
                    "target-row",
                    0.80,
                    "Value: Target answer",
                    parent_text=parent_text,
                    parent_page_start=1,
                )
            ],
            token_budget=4000,
            limit=1,
            broader_table_context=True,
        )

        self.assertLessEqual(
            len(evidence[0].payload["text"]), PARENT_PROMOTION_MAX_CHARS
        )
        self.assertIn("Target answer", evidence[0].payload["text"])

    def test_distinct_parent_windows_from_same_parent_are_kept(self) -> None:
        parent_text = (
            "First answer: Alpha "
            + ("middle filler " * 500)
            + "Second answer: Bravo "
            + ("tail filler " * 500)
        )
        hits = [
            hit(
                "alpha-row",
                0.90,
                "Value: First answer: Alpha",
                parent_chunk_id="table-1",
                parent_text=parent_text,
                parent_page_start=1,
            ),
            hit(
                "bravo-row",
                0.80,
                "Value: Second answer: Bravo",
                parent_chunk_id="table-1",
                parent_text=parent_text,
                parent_page_start=1,
            ),
        ]

        evidence = build_evidence_hits(
            hits, token_budget=4000, limit=2, broader_table_context=True
        )

        self.assertEqual(
            [item.payload["chunk_id"] for item in evidence], ["alpha-row", "bravo-row"]
        )
        self.assertIn("First answer: Alpha", evidence[0].payload["text"])
        self.assertIn("Second answer: Bravo", evidence[1].payload["text"])

    def test_exhaustive_scope_evidence_keeps_retrieved_order(self) -> None:
        hits = [
            hit(
                "doc-a:1",
                0.90,
                "A first",
                doc_id="doc-a",
                exhaustive_scope_origin="document_class_scope",
            ),
            hit(
                "doc-a:2",
                0.89,
                "A second",
                doc_id="doc-a",
                exhaustive_scope_origin="document_class_scope",
            ),
            hit(
                "doc-a:3",
                0.88,
                "A third",
                doc_id="doc-a",
                exhaustive_scope_origin="document_class_scope",
            ),
            hit(
                "doc-b:1",
                0.50,
                "B first",
                doc_id="doc-b",
                exhaustive_scope_origin="document_class_scope",
            ),
            hit(
                "doc-c:1",
                0.40,
                "C first",
                doc_id="doc-c",
                exhaustive_scope_origin="document_class_scope",
            ),
        ]

        evidence = build_evidence_hits(hits, token_budget=4000, limit=3)

        self.assertEqual(
            [item.payload["chunk_id"] for item in evidence],
            ["doc-a:1", "doc-a:2", "doc-a:3"],
        )

    def test_identical_text_in_distinct_documents_preserves_document_coverage(
        self,
    ) -> None:
        evidence = build_evidence_hits(
            [
                hit("shared", 0.90, "Required safety notice", doc_id="doc-a"),
                hit("shared", 0.80, "Required safety notice", doc_id="doc-b"),
            ],
            token_budget=4000,
            limit=2,
            query="required safety notice",
        )

        self.assertEqual(
            [item.payload["doc_id"] for item in evidence],
            ["doc-a", "doc-b"],
        )

    def test_oversized_first_hit_is_skipped(self) -> None:
        hits = [
            hit("huge", 1.00, "x" * 2000),
            hit("small", 0.90, "Relevant answer."),
        ]

        evidence = build_evidence_hits(hits, token_budget=100, limit=2)

        self.assertEqual([item.payload["chunk_id"] for item in evidence], ["small"])

    def test_high_ranked_plain_text_stays_before_structured_context(self) -> None:
        parent_text = "| Item | Page |\n| --- | --- |\n| Legal Proceedings | 18 |"
        hits = [
            hit(
                "image:0",
                1.00,
                "Image description:\nA soldier is handling ammunition while another operates artillery.",
                doc_id="image",
            ),
            hit(
                "table-row",
                0.50,
                "[Columns: Item | Page]\nRow: Item 3.\nValue: Legal Proceedings | 18",
                doc_id="report",
                chunk_type="table_row",
                parent_chunk_id="table-1",
                parent_text=parent_text,
                parent_page_start=1,
                structured_kind="table_row",
            ),
        ]

        evidence = build_evidence_hits(hits, token_budget=4000, limit=2)

        self.assertEqual(evidence[0].payload["chunk_id"], "image:0")
        self.assertIn("soldier", evidence[0].payload["text"].lower())

    def test_coverage_reserve_keeps_lower_ranked_table_row(self) -> None:
        hits = [
            hit("intro", 1.00, "This page explains unrelated document routing rules."),
            hit("summary", 0.95, "A narrative paragraph about employee onboarding."),
            hit(
                "jayantha-row",
                0.20,
                "[Columns: Employee Name | Service Number | Role]\n"
                "Row: H. C. Jayantha\n"
                "Value: Service Number: 008301 | Role: Field officer",
                chunk_type="table_row",
                structured_kind="table_row",
                structured_fields=[
                    {"label": "Employee Name", "value": "H. C. Jayantha"},
                    {"label": "Service Number", "value": "008301"},
                ],
            ),
        ]

        evidence = build_evidence_hits(
            hits,
            token_budget=4000,
            limit=2,
            query="What is the service number for H C Jayantha in the table?",
        )

        self.assertEqual(
            [item.payload["chunk_id"] for item in evidence], ["intro", "jayantha-row"]
        )

    def test_coverage_reserve_keeps_lower_ranked_exact_identifier(self) -> None:
        hits = [
            hit("top", 1.00, "A general status note with no matching identifier."),
            hit("middle", 0.95, "Another nearby paragraph without the requested code."),
            hit(
                "exact",
                0.10,
                "Packet reference ID: SD19-0042. Top fields are name, date, and amount.",
            ),
        ]

        evidence = build_evidence_hits(
            hits,
            token_budget=4000,
            limit=2,
            query="Which fields are listed for packet SD19-0042?",
        )

        self.assertEqual(
            [item.payload["chunk_id"] for item in evidence], ["top", "exact"]
        )


if __name__ == "__main__":
    unittest.main()
