from types import SimpleNamespace

from rag.query.evidence_quality import assess_evidence_quality
from rag.query.qdrant import SearchHit


def hit(point_id: str, *, doc_id: str, doc_title: str, text: str, score: float = 0.5, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=score,
        payload={
            "doc_id": doc_id,
            "chunk_id": point_id,
            "doc_title": doc_title,
            "text": text,
            "page": 1,
            **payload,
        },
    )


def test_aggregation_scores_breadth_and_document_class_above_token_overlap() -> None:
    hits = [
        hit("fir-1", doc_id="fir-1", doc_title="FIR_01.pdf", text="Robbery under section 392.", chunk_type="table_row"),
        hit("fir-2", doc_id="fir-2", doc_title="FIR_02.pdf", text="Kidnapping for ransom.", chunk_type="table_row"),
        hit("fir-3", doc_id="fir-3", doc_title="FIR_03.pdf", text="Cyber stalking and personation.", chunk_type="table_row"),
        hit("fir-4", doc_id="fir-4", doc_title="FIR_04.pdf", text="Narcotics trafficking.", chunk_type="table_row"),
    ]

    quality = assess_evidence_quality(
        "summarize every unresolved financial allegation status motive outcome in FIRs",
        hits,
        route_plan=SimpleNamespace(intent="aggregation"),
    )

    assert quality.outcome == "pass"
    assert quality.quality == "supported"
    assert quality.query_token_coverage < 0.5
    assert quality.distinct_doc_count == 4
    assert quality.document_class_match_count == 4
    assert quality.structured_hit_count == 4
    assert quality.in_scope_doc_ids == frozenset({"fir-1", "fir-2", "fir-3", "fir-4"})


def test_factual_route_still_degrades_unrelated_low_overlap_evidence() -> None:
    quality = assess_evidence_quality(
        "what is vacation policy",
        [hit("manual-1", doc_id="manual", doc_title="Server manual.pdf", text="Rail kit installation steps.", score=0.35)],
        route_plan=SimpleNamespace(intent="factual_simple"),
    )

    assert quality.outcome == "degrade"
    assert quality.quality == "weak"


def test_factual_route_passes_directly_supported_evidence() -> None:
    quality = assess_evidence_quality(
        "what is vacation policy",
        [hit("policy-1", doc_id="policy", doc_title="HR policy.pdf", text="Vacation requests require manager approval.")],
        route_plan=SimpleNamespace(intent="factual_simple"),
    )

    assert quality.outcome == "pass"
    assert quality.quality == "supported"
