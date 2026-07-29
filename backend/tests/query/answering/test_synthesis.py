from time import perf_counter

from rag.auth.context import UserContext
from rag.query.qdrant import SearchHit
from rag.query.ollama import (
    ANSWER_NUM_PREDICT,
    FACTUAL_ANSWER_NUM_PREDICT,
    LONG_ANSWER_NUM_PREDICT,
    SYNTHESIS_PROMPT_HEADROOM_TOKENS,
    answer_num_predict_for_profile,
    build_answer_prompt,
    estimate_answer_prompt_tokens,
)
from rag.query.answering.evidence_sufficiency import EvidenceSufficiencyResult
from rag.query.routing.routing_models import RoutePlan
from rag.query.sources import sources_from_hits
from rag.query.state import QueryContext, initial_state
from rag.query.answering.synthesis import (
    ensure_answer_has_citation,
    is_global_abstention,
    prepare_synthesis_input,
    synthesize_response,
)
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


def _partial_exhaustive_context() -> QueryContext:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list every repair tool"),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        capabilities=("general_search", "structured_query", "document_search"),
        scope="corpus",
        coverage="exhaustive",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit(
            "manual:tools",
            doc_id="manual",
            doc_title="Repair Manual.pdf",
            text="Hammer",
        )
    ]
    ctx["exhaustive_coverage"] = {
        "candidate_status": "complete",
        "evidence_status": "partial",
        "reasons": ["final_evidence_coverage_incomplete"],
        "required_obligations": ["section:tools", "section:safety"],
        "covered_obligations": ["section:tools"],
    }
    ctx["degraded"] = True
    ctx["degraded_reason"] = "exhaustive_final_evidence_coverage_partial"
    return ctx


def test_scoped_aggregation_synthesis_requires_document_coverage() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list all findings from all reports"),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        capabilities=("general_search", "structured_query", "document_search"),
        scope="corpus",
        coverage="exhaustive",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit(
            "report-a:1", doc_id="report-a", doc_title="Report A.pdf", text="Finding A."
        ),
        hit(
            "report-b:1", doc_id="report-b", doc_title="Report B.pdf", text="Finding B."
        ),
    ]

    prepared = prepare_synthesis_input(
        ctx, sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query)
    )

    assert "Evidence scope: exhaustive document-class scan." in prepared.question
    assert "Report A.pdf" in prepared.question
    assert "Report B.pdf" in prepared.question
    assert (
        "Cover every scoped document represented in the evidence" in prepared.question
    )
    assert any(
        "Location: Document: Report A.pdf" in context for context in prepared.contexts
    )


def test_partial_exhaustive_scope_forbids_complete_inventory_claims() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list every finding"),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        capabilities=("general_search", "structured_query", "document_search"),
        scope="corpus",
        coverage="exhaustive",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit(
            "report-a:1",
            doc_id="report-a",
            doc_title="Report A.pdf",
            text="Finding A.",
        )
    ]
    ctx["degraded"] = True
    ctx["degraded_reason"] = "exhaustive_candidate_coverage_partial"

    prepared = prepare_synthesis_input(
        ctx,
        sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query),
    )

    assert (
        "Evidence scope: incomplete exhaustive document-class scan."
        in prepared.question
    )
    assert "Label the answer as partial" in prepared.question
    assert "Do not claim that the result contains all" in prepared.question


def test_partial_answer_rewrites_universal_inventory_claim() -> None:
    ctx = synthesize_response(
        _partial_exhaustive_context(),
        FakeLlm("All required equipment: Hammer."),
    )

    response = ctx["response"]

    assert response.answer.startswith("Partial result")
    assert "All required equipment" not in response.answer
    assert "Retrieved required equipment: Hammer." in response.answer
    assert response.answer_status == "partial"
    assert response.coverage.completeness == "partial"


def test_partial_answer_rewrites_unsupported_exclusivity_claim() -> None:
    ctx = synthesize_response(
        _partial_exhaustive_context(),
        FakeLlm(
            "Hammer is listed. Nothing else is required beyond Hammer [manual:tools]."
        ),
    )

    answer = ctx["response"].answer

    assert "Nothing else is required" not in answer
    assert (
        "Additional items may exist outside the retrieved evidence [manual:tools]."
        in answer
    )


def test_partial_answer_preserves_non_inventory_use_of_all() -> None:
    ctx = synthesize_response(
        _partial_exhaustive_context(),
        FakeLlm("Wear gloves at all times."),
    )

    assert "Wear gloves at all times." in ctx["response"].answer


def test_structured_exhaustive_status_survives_other_degradation_reasons() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list every finding"),
        user=UserContext(
            user_id="user",
            email="user@example.com",
            group_paths=("/admin",),
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        capabilities=("general_search", "structured_query", "document_search"),
        scope="corpus",
        coverage="exhaustive",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit(
            "report-a:1",
            doc_id="report-a",
            doc_title="Report A.pdf",
            text="Finding A.",
        )
    ]
    ctx["degraded"] = True
    ctx["degraded_reason"] = "Insufficient relevant evidence after retrieval retries"
    ctx["exhaustive_coverage"] = {
        "candidate_status": "complete",
        "evidence_status": "partial",
        "reasons": ["final_evidence_coverage_incomplete"],
        "required_obligations": ["unit:report-a", "unit:report-b"],
        "covered_obligations": ["unit:report-a"],
    }

    prepared = prepare_synthesis_input(
        ctx,
        sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query),
    )

    assert (
        "Evidence scope: incomplete exhaustive document-class scan."
        in prepared.question
    )
    assert "Label the answer as partial" in prepared.question


def test_partial_coverage_is_enforced_in_answer_and_response_contract() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list every tool"),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        capabilities=("general_search", "structured_query", "document_search"),
        scope="corpus",
        coverage="exhaustive",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit(
            "manual:tools",
            doc_id="manual",
            doc_title="Manual.pdf",
            text="Hammer",
        )
    ]
    ctx["exhaustive_coverage"] = {
        "candidate_status": "complete",
        "evidence_status": "partial",
        "reasons": ["final_evidence_coverage_incomplete"],
        "required_obligations": ["unit:tools", "page:manual:2"],
        "covered_obligations": ["unit:tools"],
    }

    synthesize_response(ctx, FakeLlm("This is the complete list: Hammer."))

    response = ctx["response"]
    assert response.answer_status == "partial"
    assert response.coverage.completeness == "partial"
    assert response.coverage.required_slots == ["unit:tools", "page:manual:2"]
    assert response.coverage.covered_slots == ["unit:tools"]
    assert response.answer.startswith("Partial result")
    assert "complete list" not in response.answer.lower()


def test_unresolved_exhaustive_scope_returns_clarification_status() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list all equipment from Acme manual"),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        capabilities=("general_search", "structured_query", "document_search"),
        scope="corpus",
        coverage="exhaustive",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["exhaustive_coverage"] = {
        "candidate_status": "complete",
        "evidence_status": "unknown",
        "reasons": ["scope_unresolved"],
        "required_obligations": [],
        "covered_obligations": [],
    }

    synthesize_response(ctx, FakeLlm("unused"))

    response = ctx["response"]
    assert response.answer_status == "clarification"
    assert response.coverage.completeness == "unknown"
    assert "Please select a document" in response.answer


def test_synthesis_contexts_fit_final_prompt_budget() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="list all findings from all reports"),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=perf_counter(),
        token_budget=3200,
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="aggregation",
        capabilities=("general_search", "structured_query", "document_search"),
        scope="corpus",
        coverage="exhaustive",
        public_intent="aggregation",
        top_k=24,
    )
    ctx["retrieved_hits"] = [
        hit(
            "report-a:1",
            doc_id="report-a",
            doc_title="Report A.pdf",
            text="Finding A. " * 80,
        ),
        hit(
            "report-b:1",
            doc_id="report-b",
            doc_title="Report B.pdf",
            text="Finding B. " * 80,
        ),
        hit(
            "report-c:1",
            doc_id="report-c",
            doc_title="Report C.pdf",
            text="Finding C. " * 80,
        ),
    ]
    sources = sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query)

    prepared = prepare_synthesis_input(ctx, sources)

    assert len(prepared.contexts) < len(sources)
    assert len(prepared.contexts) == len(prepared.sources)
    assert ctx["synthesis_context_count"] == len(prepared.contexts)
    assert ctx["synthesis_estimated_prompt_tokens"] == estimate_answer_prompt_tokens(
        question=prepared.question,
        contexts=prepared.contexts,
        profile=prepared.profile,
    )
    assert prepared.sources[0].doc_id == "report-a"
    assert (
        estimate_answer_prompt_tokens(
            question=prepared.question,
            contexts=prepared.contexts,
            profile=prepared.profile,
        )
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
    legacy_prompt = build_answer_prompt(
        question="What is the status?", contexts=contexts
    )

    assert "For highest/lowest/max/min" not in factual_prompt
    assert "Treat named table rows" not in factual_prompt
    assert len(factual_prompt) < len(legacy_prompt)


def test_answer_prompt_forbids_citation_only_output() -> None:
    prompt = build_answer_prompt(
        question="What is the status?",
        contexts=["[doc:1]\nStatus: Open."],
        profile="factual_simple",
    )

    assert "Never return a citation alone" in prompt


def test_answer_prompt_defaults_to_detailed_grounded_response() -> None:
    prompt = build_answer_prompt(
        question="Explain the approval process.",
        contexts=["[policy:1]\nA manager reviews the request before finance approves it."],
        profile="procedural",
    )

    assert "Lead with the direct answer" in prompt
    assert "details, reasons, relationships, conditions, exceptions, and examples" in prompt
    assert "Unless the user asks for brevity, be descriptive and complete" in prompt
    assert "stop after the direct answer" not in prompt


def test_citation_only_database_answer_uses_structured_row_fallback() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(
            query="Which demo case has the highest priority? Return its case ID, status, assigned team, and outstanding amount."
        ),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=perf_counter(),
    )
    citation = "[connector-live-scope:catalog:query:0]"
    ctx["retrieved_hits"] = [
        SearchHit(
            point_id="connector-live-scope:catalog:query:0",
            score=1.0,
            payload={
                "doc_id": "connector-live-scope:catalog",
                "chunk_id": "connector-live-scope:catalog:query:0",
                "doc_title": "Live connector query: Demo cases",
                "text": "case_id: DEMO-ALPHA\nstatus: Escalated\nassigned_team: Phoenix\noutstanding_amount: 1250.75",
                "source_type": "connector_live_sql_database_scope",
                "structured_kind": "kv_record",
                "structured_fields": [
                    {"label": "case_id", "value": "DEMO-ALPHA"},
                    {"label": "status", "value": "Escalated"},
                    {"label": "assigned_team", "value": "Phoenix"},
                    {"label": "outstanding_amount", "value": "1250.75"},
                ],
            },
        )
    ]

    synthesize_response(ctx, FakeLlm(citation))

    response = ctx["response"]
    assert response.answer == (
        "case_id: DEMO-ALPHA; status: Escalated; assigned_team: Phoenix; "
        f"outstanding_amount: 1250.75 {citation}."
    )
    assert response.answer_status == "complete"
    assert not response.degraded


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

    assert (
        "| case_number | title | status | priority | lead_officer | evidence_count |"
        in cited
    )
    assert (
        "| case_number | title | status | priority | lead_officer | evidence_count | [live:row-1]"
        not in cited
    )
    assert (
        "| CASE-2026-014 | Suspicious vendor payment chain | Open | High | Maya Chen | 1 [live:row-1] |"
        in cited
    )


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
    assert (
        "| CASE-2026-014 | Suspicious vendor payment chain | 1 [live:row-1] |" in cited
    )


def test_table_context_keeps_table_guidance_for_factual_profile() -> None:
    prompt = build_answer_prompt(
        question="What is Ali's status?",
        contexts=[
            "[doc:1]\n[Columns: Name | Status]\nRow: Name: Ali\nValue: Status: Open"
        ],
        profile="factual_simple",
    )

    assert "For table Row/Value evidence" in prompt
    assert "Treat named table rows" in prompt


def test_answer_generation_uses_route_appropriate_output_budget() -> None:
    assert ANSWER_NUM_PREDICT == 1024
    assert FACTUAL_ANSWER_NUM_PREDICT == ANSWER_NUM_PREDICT
    assert (
        answer_num_predict_for_profile("factual_simple")
        == FACTUAL_ANSWER_NUM_PREDICT
    )
    for profile in (
        "general_rag",
        "procedural",
        "summarization",
        "troubleshooting",
        "troubleshooting_procedure",
    ):
        assert answer_num_predict_for_profile(profile) == LONG_ANSWER_NUM_PREDICT


def test_deterministic_factual_synthesis_uses_all_sources_that_fit_prompt_budget() -> None:
    query = "What is the account code for Vega?"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=query,
        resolved_query=query,
        intent="general_rag",
        capabilities=("general_search",),
        response_mode="lookup",
    )
    ctx["evidence_sufficiency"] = EvidenceSufficiencyResult(
        relevance="relevant",
        sufficiency="sufficient",
        supported_aspects=("matched structured field",),
        missing_aspects=(),
        action="answer",
        evaluator_status="not_needed",
    )
    ctx["retrieved_hits"] = [
        hit(
            f"account:{index}",
            doc_id="account",
            doc_title="Vega account record",
            text=f"Account evidence {index}",
        )
        for index in range(5)
    ]
    sources = sources_from_hits(ctx["retrieved_hits"], query=query)

    prepared = prepare_synthesis_input(ctx, sources)

    assert prepared.sources == sources
    assert len(prepared.contexts) == len(sources) == 5


def test_documents_do_not_contain_information_is_global_abstention() -> None:
    assert is_global_abstention(
        "The documents do not contain information about soldiers or their activities."
    )


def test_mixed_abstention_with_supported_value_keeps_sources() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="What service number is written for H.C. Jayantha?"),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
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
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
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

    synthesize_response(
        ctx, FakeLlm("The indexed sources do not contain enough information.")
    )

    response = ctx["response"]
    assert not response.degraded
    assert response.sources
    assert "HANDWRITING SAMPLE FORM" in response.answer
    assert "[sd19:1]" in response.answer


def test_definition_abstention_uses_sentence_fallback() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(
            query="How does the Zero Trust Maturity Model define a device?"
        ),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
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
        ),
    ]

    synthesize_response(
        ctx, FakeLlm("The indexed sources do not contain enough information.")
    )

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
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
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

    synthesize_response(
        ctx, FakeLlm("The indexed sources do not contain enough information.")
    )

    response = ctx["response"]
    assert response.degraded
    assert response.sources
    assert "[sd19:1]" in response.answer


def test_cited_insufficient_fallback_prefers_named_document() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(
            query="What handwritten value appears under the printed label 960941 on sd19.pdf?"
        ),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
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

    synthesize_response(
        ctx, FakeLlm("The indexed sources do not contain enough information.")
    )

    response = ctx["response"]
    assert response.degraded
    assert response.sources[0].doc_title == "sd19.pdf"
    assert "[sd19:1]" in response.answer
