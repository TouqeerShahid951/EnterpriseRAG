import json
from time import perf_counter
from unittest.mock import Mock

from rag.query.answering.citation_claims import answer_claims
from rag.query.evidence_validation import VerificationBudget, validate_claims
from rag.shared.contracts.evidence import SourceAnchor


def test_citation_boundaries_keep_offsets_labels_and_uncited_facts():
    answer = "Dr. A. pays 2.5 USD. [doc:1] [doc:2] Notice is 30 days [doc:3]. Unless both parties agree otherwise. [doc:4] Uncited final fact."
    claims = answer_claims(answer)
    assert len(claims) == 3
    assert claims[0].source_labels == ["[doc:1]", "[doc:2]"]
    assert claims[1].source_labels == ["[doc:3]", "[doc:4]"]
    assert "Unless both parties" in claims[1].text
    assert claims[2].source_labels == []
    assert "".join(answer[c.answer_start:c.answer_end] for c in claims) == answer


def test_compound_sentence_and_table_rows_keep_their_context():
    answer = "Payment is required [doc:1], except during suspension [doc:2]."
    assert len(answer_claims(answer)) == 1
    table = "| Term | Value |\n| --- | --- |\n| Fee | 2.5 USD. [doc:1] Notice is 30 days. [doc:2] |"
    claims = answer_claims(table)
    assert len(claims) == 1
    assert claims[0].text.startswith("Columns: | Term | Value |")
    assert claims[0].source_labels == ["[doc:1]", "[doc:2]"]


def test_twelve_source_summary_accepts_exact_quotes_without_format_retry():
    sources = [SourceAnchor(
        doc_id="contract", chunk_id=f"contract:{i}", doc_title="Synthetic contract",
        excerpt=f"Term {i} requires notice.", provenance_kind="native", group_path="/local",
    ) for i in range(12)]
    labels = [f"[contract:{i}]" for i in range(12)]
    answer = "All twelve terms require notice. " + " ".join(labels)
    claims = answer_claims(answer)
    assert len(claims) == 1
    raw = {"responsive": True, "missing_aspects": [], "claims": [{
        "claim_id": "claim-1", "verdict": "supported", "quotes": [
            {"source_label": label, "quote": source.excerpt}
            for label, source in zip(labels, sources, strict=True)
        ],
    }]}
    judge = Mock(return_value=json.dumps(raw))
    budget = VerificationBudget(perf_counter() + 10)
    checked = validate_claims(claims, sources, question="Summarize", answer=answer, generate=judge, budget=budget)
    assert checked[0].verdict == "supported"
    assert len(checked[0].quotes) == 12
    assert budget.calls == 1 and budget.format_retries == 0
    assert judge.call_args.kwargs["json_schema"]["properties"]["claims"]["items"]["properties"]["quotes"]["maxItems"] == 12
    assert judge.call_args.kwargs["max_tokens"] <= budget.output_tokens
    # Raising capacity must not let invented quotes through.
    raw["claims"][0]["quotes"][0]["quote"] = "Fabricated clause."
    checked = validate_claims(claims, sources, question="Summarize", answer=answer,
                              generate=Mock(return_value=json.dumps(raw)), budget=VerificationBudget(perf_counter() + 10))
    assert checked[0].verdict == "unknown"
    assert checked[0].reason == "quote_not_found_or_ambiguous"


def test_many_source_unit_that_cannot_fit_fails_without_a_provider_call():
    labels = [f"[doc:{i}]" for i in range(17)]
    sources = [SourceAnchor(doc_id="doc", chunk_id=f"doc:{i}", doc_title="Test",
                           excerpt="A " * 400, provenance_kind="native", group_path="/local") for i in range(17)]
    judge = Mock()
    answer = "A compound statement. " + " ".join(labels)
    checked = validate_claims(answer_claims(answer), sources, question="Test", answer=answer,
                              generate=judge, budget=VerificationBudget(perf_counter() + 10, output_tokens=1024))
    assert checked[0].verdict == "unknown"
    judge.assert_not_called()
