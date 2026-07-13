from time import perf_counter

from rag.auth.context import UserContext
from rag.query.qdrant import SearchHit
from rag.query.ollama import (
    ANSWER_NUM_PREDICT,
    LONG_ANSWER_NUM_PREDICT,
    SYNTHESIS_PROMPT_HEADROOM_TOKENS,
    answer_num_predict_for_profile,
    build_answer_prompt,
    estimate_answer_prompt_tokens,
)
from rag.query.routing_models import RoutePlan
from rag.query.sources import sources_from_hits
from rag.query.state import initial_state
from rag.query.synthesis import ensure_answer_has_citation, is_global_abstention, prepare_synthesis_input, synthesize_response
from rag.query.schemas import QueryRequest


def hit(point_id: str, *, doc_id: str, doc_title: str, text: str) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=0.5,
        payload={
            "doc_id": doc_id,
            "chunk_id": point_id,
            "doc_title": doc_title,
            "text": text,
            "page": 1,
            "exhaustive_scope_origin": "document_class_scope",
        },
    )


class FakeLlm:
    def __init__(self, answer: str) -> None:
        self.answer_text = answer

    def answer(self, **_: object) -> str:
        return self.answer_text


def test_scoped_aggregation_synthesis_requires_document_coverage() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list all findings from all reports"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit("report-a:1", doc_id="report-a", doc_title="Report A.pdf", text="Finding A."),
        hit("report-b:1", doc_id="report-b", doc_title="Report B.pdf", text="Finding B."),
    ]

    prepared = prepare_synthesis_input(ctx, sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query))

    assert "Evidence scope: exhaustive document-class scan." in prepared.question
    assert "Report A.pdf" in prepared.question
    assert "Report B.pdf" in prepared.question
    assert "Cover every scoped document represented in the evidence" in prepared.question
    assert any("Location: Document: Report A.pdf" in context for context in prepared.contexts)


def test_synthesis_contexts_fit_final_prompt_budget() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list all findings from all reports"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
        token_budget=3200,
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit("report-a:1", doc_id="report-a", doc_title="Report A.pdf", text="Finding A. " * 80),
        hit("report-b:1", doc_id="report-b", doc_title="Report B.pdf", text="Finding B. " * 80),
        hit("report-c:1", doc_id="report-c", doc_title="Report C.pdf", text="Finding C. " * 80),
    ]
    sources = sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query)

    prepared = prepare_synthesis_input(ctx, sources)

    assert len(prepared.contexts) < len(sources)
    assert len(prepared.contexts) == len(prepared.sources)
    assert prepared.sources[0].doc_id == "report-a"
    assert (
        estimate_answer_prompt_tokens(question=prepared.question, contexts=prepared.contexts, profile=prepared.profile)
        + answer_num_predict_for_profile(prepared.profile)
        + SYNTHESIS_PROMPT_HEADROOM_TOKENS
        <= ctx["token_budget"]
    )


def test_factual_answer_prompt_omits_structured_guidance() -> None:
    contexts = ["[doc:1]\nStatus: Open."]

    factual_prompt = build_answer_prompt(
        question="What is the status?",
        contexts=contexts,
        profile="factual_simple",
    )
    legacy_prompt = build_answer_prompt(question="What is the status?", contexts=contexts)

    assert "For highest/lowest/max/min" not in factual_prompt
    assert "Treat named table rows" not in factual_prompt
    assert len(factual_prompt) < len(legacy_prompt)


def test_auto_citations_preserve_markdown_table_syntax() -> None:
    sources = sources_from_hits(
        [
            hit(
                "live:row-1",
                doc_id="live",
                doc_title="Live DB",
                text="CASE-2026-014 Suspicious vendor payment chain Open High Maya Chen evidence_count 1.",
            )
        ],
        query="case table",
    )
    answer = "\n".join(
        [
            "| case_number | title | status | priority | lead_officer | evidence_count |",
            "| --- | --- | --- | --- | --- | --- |",
            "| CASE-2026-014 | Suspicious vendor payment chain | Open | High | Maya Chen | 1 |",
        ]
    )

    cited = ensure_answer_has_citation(answer, sources)

    assert "| case_number | title | status | priority | lead_officer | evidence_count |" in cited
    assert "| case_number | title | status | priority | lead_officer | evidence_count | [live:row-1]" not in cited
    assert "| CASE-2026-014 | Suspicious vendor payment chain | Open | High | Maya Chen | 1 [live:row-1] |" in cited


def test_auto_citations_normalize_trailing_table_row_citation() -> None:
    sources = sources_from_hits(
        [
            hit(
                "live:row-1",
                doc_id="live",
                doc_title="Live DB",
                text="CASE-2026-014 Suspicious vendor payment chain Open High Maya Chen evidence_count 1.",
            )
        ],
        query="case table",
    )
    answer = "\n".join(
        [
            "| case_number | title | evidence_count | [live:row-1]",
            "| --- | --- | --- |",
            "| CASE-2026-014 | Suspicious vendor payment chain | 1 | [live:row-1]",
        ]
    )

    cited = ensure_answer_has_citation(answer, sources)

    assert "| case_number | title | evidence_count |" in cited
    assert "| case_number | title | evidence_count | [live:row-1]" not in cited
    assert "| CASE-2026-014 | Suspicious vendor payment chain | 1 [live:row-1] |" in cited


def test_table_context_keeps_table_guidance_for_factual_profile() -> None:
    prompt = build_answer_prompt(
        question="What is Ali's status?",
        contexts=["[doc:1]\n[Columns: Name | Status]\nRow: Name: Ali\nValue: Status: Open"],
        profile="factual_simple",
    )

    assert "For table Row/Value evidence" in prompt
    assert "Treat named table rows" in prompt


def test_answer_generation_uses_fast_output_budget() -> None:
    assert ANSWER_NUM_PREDICT == 1024
    assert answer_num_predict_for_profile("factual_simple") == ANSWER_NUM_PREDICT
    assert answer_num_predict_for_profile("summarization") == LONG_ANSWER_NUM_PREDICT


def test_documents_do_not_contain_information_is_global_abstention() -> None:
    assert is_global_abstention("The documents do not contain information about soldiers or their activities.")


def test_mixed_abstention_with_supported_value_keeps_sources() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="What service number is written for H.C. Jayantha?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["retrieved_hits"] = [
        hit(
            "doc:1",
            doc_id="doc",
            doc_title="handwritten table.pdf",
            text="Visible image text: O2 H.C.Jayawick 008301 T.M/ORaLm",
        )
    ]

    synthesize_response(
        ctx,
        FakeLlm(
            'The indexed sources do not contain enough information. The provided evidence lists "H.C.Jayawick" '
            "with service number 008301."
        ),
    )

    response = ctx["response"]
    assert not response.degraded
    assert response.sources
    assert "[doc:1]" in response.answer


def test_title_abstention_uses_heading_fallback() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="What is the title at the top of sd19.pdf?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["retrieved_hits"] = [
        hit(
            "sd19:1",
            doc_id="sd19",
            doc_title="sd19.pdf",
            text="## HANDWRITING SAMPLE FORM\n\nPlease print the following text in the box below.",
        )
    ]

    synthesize_response(ctx, FakeLlm("The indexed sources do not contain enough information."))

    response = ctx["response"]
    assert not response.degraded
    assert response.sources
    assert "HANDWRITING SAMPLE FORM" in response.answer
    assert "[sd19:1]" in response.answer


def test_definition_abstention_uses_sentence_fallback() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="How does the Zero Trust Maturity Model define a device?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["retrieved_hits"] = [
        hit(
            "ztmm:45",
            doc_id="ztmm",
            doc_title="zero_trust_maturity_model_v2_508.pdf",
            text="The Zero Trust Maturity Model is one path to support the transition to zero trust.",
        ),
        hit(
            "ztmm:98",
            doc_id="ztmm",
            doc_title="zero_trust_maturity_model_v2_508.pdf",
            text=(
                "5.2 Devices\n\n"
                "A device refers to any asset, including hardware, software, firmware, and more, "
                "that can connect to a network."
            ),
        )
    ]

    synthesize_response(ctx, FakeLlm("The indexed sources do not contain enough information."))

    response = ctx["response"]
    assert not response.degraded
    assert "hardware, software, firmware" in response.answer
    assert "network" in response.answer
    assert "[ztmm:98]" in response.answer


def test_unanswered_evidence_present_abstention_keeps_cited_source() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="What digit sequence is printed in the top boxes?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["retrieved_hits"] = [
        hit(
            "sd19:1",
            doc_id="sd19",
            doc_title="sd19.pdf",
            text="## HANDWRITING SAMPLE FORM\n\nPlease print the following text in the box below.",
        )
    ]

    synthesize_response(ctx, FakeLlm("The indexed sources do not contain enough information."))

    response = ctx["response"]
    assert response.degraded
    assert response.sources
    assert "[sd19:1]" in response.answer


def test_cited_insufficient_fallback_prefers_named_document() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="What handwritten value appears under the printed label 960941 on sd19.pdf?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=perf_counter(),
    )
    ctx["retrieved_hits"] = [
        hit(
            "table:1",
            doc_id="table",
            doc_title="handwritten-table.pdf",
            text="Visible image text: handwritten entries and service numbers.",
        ),
        hit(
            "sd19:1",
            doc_id="sd19",
            doc_title="sd19.pdf",
            text="## HANDWRITING SAMPLE FORM\n\nPlease print the following text in the box below.",
        ),
    ]

    synthesize_response(ctx, FakeLlm("The indexed sources do not contain enough information."))

    response = ctx["response"]
    assert response.degraded
    assert response.sources[0].doc_title == "sd19.pdf"
    assert "[sd19:1]" in response.answer
