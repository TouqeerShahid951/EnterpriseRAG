from __future__ import annotations

import unittest

from rag.query.qdrant import SearchHit
from rag.query.sources import build_evidence_hits


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


class EvidenceBuilderTests(unittest.TestCase):
    def test_structured_row_preserves_parent_table_context_before_isolated_rows(self) -> None:
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
                    {"label": "Case Information", "value": "Contact Numbers: 03009876543"},
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

        evidence = build_evidence_hits(hits, token_budget=4000, limit=1)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].payload["structured_origin"], "context")
        self.assertIn("Name(s): Sajjad Hussain", evidence[0].payload["text"])
        self.assertIn("Contact Numbers: 03009876543", evidence[0].payload["text"])

    def test_exhaustive_scope_evidence_round_robins_across_documents(self) -> None:
        hits = [
            hit("doc-a:1", 0.90, "A first", doc_id="doc-a", exhaustive_scope_origin="document_class_scope"),
            hit("doc-a:2", 0.89, "A second", doc_id="doc-a", exhaustive_scope_origin="document_class_scope"),
            hit("doc-a:3", 0.88, "A third", doc_id="doc-a", exhaustive_scope_origin="document_class_scope"),
            hit("doc-b:1", 0.50, "B first", doc_id="doc-b", exhaustive_scope_origin="document_class_scope"),
            hit("doc-c:1", 0.40, "C first", doc_id="doc-c", exhaustive_scope_origin="document_class_scope"),
        ]

        evidence = build_evidence_hits(hits, token_budget=4000, limit=3)

        self.assertEqual([item.payload["doc_id"] for item in evidence], ["doc-a", "doc-b", "doc-c"])


if __name__ == "__main__":
    unittest.main()
