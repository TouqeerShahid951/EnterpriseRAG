import json
import re
from dataclasses import replace
from time import perf_counter

import pytest

from rag.auth.context import UserContext
from rag.query.cancellation import QueryCancellationToken, QueryCancelled
from rag.query.answering.synthesis import prepare_synthesis_input
from rag.query.qdrant import SearchHit
from rag.query.routing.routing_models import RoutePlan
from rag.query.schemas import QueryRequest
from rag.query.sources import sources_from_hits
from rag.query.state import initial_state
from rag.query.summarization import prepare_summary


class SummaryLlm:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_json(self, *, prompt: str, **_: object) -> str:
        self.calls.append(prompt)
        labels = list(dict.fromkeys(re.findall(r"\[[^\[\]\n]+:[^\[\]\n]+\]", prompt)))
        section = re.search(r"Section: ([^\n]+)", prompt)
        return json.dumps(
            {
                "summary": f"Summary for {section.group(1) if section else 'combined content'}.",
                "evidence_ids": labels,
            }
        )


def _context(*, token_budget: int = 12_000) -> dict:
    query = "Summarize this document"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query, document_ids=["report"]),
        user=UserContext(
            user_id="user", email="user@example.com", group_paths=("/admin",)
        ),
        started=perf_counter(),
        token_budget=token_budget,
    )
    ctx["route_plan"] = RoutePlan(
        original_query=query,
        resolved_query=query,
        intent="summarization",
        capabilities=("general_search", "document_search"),
        response_mode="summary",
        scope="document",
        coverage="exhaustive",
        summary_mode="document",
        public_intent="multi_hop",
        top_k=24,
    )
    return ctx


def _hit(index: int, section: str, text: str) -> SearchHit:
    return SearchHit(
        point_id=f"report:{index}",
        score=0.8,
        payload={
            "doc_id": "report",
            "doc_title": "Report.pdf",
            "chunk_id": f"report:{index}",
            "text": text,
            "page": index,
            "section_path": [section],
            "parent_section_id": section.lower(),
            "authorized_scan_complete": True,
            "exhaustive_scope_origin": "document_class_scope",
        },
    )


def test_long_document_maps_every_structural_unit_and_keeps_original_sources() -> None:
    ctx = _context()
    ctx["retrieved_hits"] = [
        _hit(1, "Beginning", "Beginning fact. " * 500),
        _hit(20, "Middle", "Middle fact. " * 500),
        _hit(40, "End", "Final fact. " * 500),
    ]
    llm = SummaryLlm()

    progress = list(prepare_summary(ctx, llm, model="summary-model"))
    prepared = prepare_synthesis_input(
        ctx, sources_from_hits(ctx["retrieved_hits"], query=ctx["request"].query)
    )

    assert len(llm.calls) == 3
    assert progress[-1]["stage"] == "summary_ready"
    assert {"Beginning", "Middle", "End"} <= {
        context.split("\n", 2)[1].removeprefix("Section: ")
        for context in prepared.contexts
    }
    assert {source.chunk_id for source in prepared.sources} == {
        "report:1",
        "report:20",
        "report:40",
    }
    assert ctx["exhaustive_coverage"]["candidate_status"] == "complete"
    assert ctx["exhaustive_coverage"]["evidence_status"] == "complete"


def test_failed_summary_unit_cannot_report_complete_coverage() -> None:
    class FailingLlm:
        def generate_json(self, **_: object) -> str:
            return '{"summary":"unsupported","evidence_ids":["[wrong:id]"]}'

    ctx = _context()
    ctx["retrieved_hits"] = [_hit(1, "Only section", "Fact. " * 4_000)]

    list(prepare_summary(ctx, FailingLlm(), model="summary-model"))

    assert ctx["summary_contexts"] == []
    assert ctx["exhaustive_coverage"]["evidence_status"] == "partial"
    assert ctx["degraded_reason"] == "summary_coverage_partial"


def test_short_document_uses_direct_context_without_model_call() -> None:
    ctx = _context()
    ctx["retrieved_hits"] = [_hit(1, "Only section", "A short supported fact.")]
    llm = SummaryLlm()

    list(prepare_summary(ctx, llm, model="summary-model"))

    assert llm.calls == []
    assert "A short supported fact" in ctx["summary_contexts"][0]
    assert ctx["exhaustive_coverage"]["evidence_status"] == "complete"


def test_multi_document_summary_reduces_each_document_separately() -> None:
    ctx = _context(token_budget=2_000)
    ctx["route_plan"] = replace(
        ctx["route_plan"], summary_mode="multi_document", scope="corpus"
    )
    ctx["retrieved_hits"] = [
        _hit(1, "Opening", "A opening. " * 500),
        _hit(2, "Closing", "A closing. " * 500),
        SearchHit(
            point_id="report-b:1",
            score=0.8,
            payload={
                **_hit(1, "Opening", "B opening. " * 500).payload,
                "doc_id": "report-b",
                "doc_title": "Report B.pdf",
                "chunk_id": "report-b:1",
                "parent_section_id": "b-opening",
            },
        ),
        SearchHit(
            point_id="report-b:2",
            score=0.8,
            payload={
                **_hit(2, "Closing", "B closing. " * 500).payload,
                "doc_id": "report-b",
                "doc_title": "Report B.pdf",
                "chunk_id": "report-b:2",
                "parent_section_id": "b-closing",
            },
        ),
    ]
    llm = SummaryLlm()

    list(prepare_summary(ctx, llm, model="summary-model"))

    assert len(ctx["summary_contexts"]) == 2
    assert any("Report.pdf" in context for context in ctx["summary_contexts"])
    assert any("Report B.pdf" in context for context in ctx["summary_contexts"])


def test_summary_stops_before_model_work_when_cancelled() -> None:
    ctx = _context(token_budget=2_000)
    ctx["retrieved_hits"] = [_hit(1, "Large", "Large fact. " * 1_000)]
    token = QueryCancellationToken()
    token.cancel()
    ctx["cancellation_token"] = token
    llm = SummaryLlm()

    with pytest.raises(QueryCancelled):
        list(prepare_summary(ctx, llm, model="summary-model"))

    assert llm.calls == []


def test_section_summary_excludes_other_sections() -> None:
    ctx = _context()
    ctx["route_plan"] = replace(
        ctx["route_plan"],
        resolved_query="Summarize chapter 8 of the document",
        summary_mode="section",
    )
    ctx["retrieved_hits"] = [
        _hit(1, "Chapter 7", "Previous chapter."),
        _hit(2, "Chapter 8", "Requested chapter."),
        _hit(3, "Chapter 9", "Following chapter."),
    ]

    list(prepare_summary(ctx, SummaryLlm(), model="summary-model"))

    assert len(ctx["summary_contexts"]) == 1
    assert "Requested chapter" in ctx["summary_contexts"][0]
    assert "Previous chapter" not in ctx["summary_contexts"][0]


def test_unresolved_section_does_not_fall_back_to_whole_document() -> None:
    ctx = _context()
    ctx["route_plan"] = replace(
        ctx["route_plan"],
        resolved_query="Summarize chapter 8 of the document",
        summary_mode="section",
    )
    ctx["retrieved_hits"] = [_hit(1, "Chapter 7", "Wrong chapter.")]

    list(prepare_summary(ctx, SummaryLlm(), model="summary-model"))

    assert ctx["summary_contexts"] == []
    assert ctx["degraded_reason"] == "section_scope_unresolved"


def test_section_two_excludes_other_numbered_headings_and_captions() -> None:
    ctx = _context()
    ctx["route_plan"] = replace(ctx["route_plan"], resolved_query="Summarize section 2.", summary_mode="section")
    ctx["retrieved_hits"] = [
        _hit(index, title, f"Fact from {title}.")
        for index, title in enumerate(["2. Audience", "2.1 Roles", "1.2.1 Risk", "5.2 Map", "Table 2: Results", "Appendix A: Figures 2 and 3"], 1)
    ]
    list(prepare_summary(ctx, SummaryLlm(), model="summary-model"))
    text = "\n".join(ctx["summary_contexts"])
    assert "Audience" in text and "Roles" in text
    assert "Risk" not in text and "Map" not in text and "Figures" not in text
    assert "Results" not in text


def test_repeated_section_numbers_under_different_chapters_are_unresolved() -> None:
    ctx = _context()
    ctx["route_plan"] = replace(ctx["route_plan"], resolved_query="Summarize section 2", summary_mode="section")
    hits = [_hit(1, "2. Scope", "Chapter one fact"), _hit(2, "2. Scope", "Chapter two fact")]
    hits[0].payload["section_path"] = ["Chapter 1", "2. Scope"]
    hits[1].payload["section_path"] = ["Chapter 2", "2. Scope"]
    ctx["retrieved_hits"] = hits
    list(prepare_summary(ctx, SummaryLlm(), model="summary-model"))
    assert ctx["summary_contexts"] == []
    assert ctx["degraded_reason"] == "section_scope_unresolved"
