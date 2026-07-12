from __future__ import annotations

from rag.query.artifact_composer import _sections_from_answer
from rag.query.artifact_intent import ArtifactRequest
from rag.query.artifact_pipeline import assess_artifact_evidence, plan_artifact_request
from rag.query.qdrant import SearchHit


def test_narrative_claim_without_explicit_citation_stays_unsupported() -> None:
    plan = plan_artifact_request(
        ArtifactRequest(
            original_query="Create a PDF summary about household cats",
            content_query="summarize household cats",
            formats=("pdf",),
        ),
        document_ids=[],
    )
    assessment = assess_artifact_evidence(
        plan,
        [
            SearchHit(
                point_id="chunk-1",
                score=0.9,
                payload={
                    "doc_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "doc_title": "Pet policy",
                    "text": "The household pet policy applies to cats.",
                },
            )
        ],
        document_ids=[],
    )

    _sections, claims = _sections_from_answer(
        "Cats are banned from Mars.",
        assessment.units,
        default_heading="Summary",
    )

    assert claims[0].support_status == "unsupported"
    assert claims[0].evidence_ids == ()


def test_selected_document_scope_does_not_bypass_objective_relevance() -> None:
    plan = plan_artifact_request(
        ArtifactRequest(
            original_query="Create a PDF summary of nuclear reactors",
            content_query="summarize nuclear reactors",
            formats=("pdf",),
        ),
        document_ids=["doc-1"],
    )

    assessment = assess_artifact_evidence(
        plan,
        [
            SearchHit(
                point_id="chunk-1",
                score=0.9,
                payload={
                    "doc_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "doc_title": "Pet policy",
                    "text": "The household pet policy applies to cats.",
                },
            )
        ],
        document_ids=["doc-1"],
    )

    assert assessment.units == ()
    assert assessment.coverage.status == "none"
