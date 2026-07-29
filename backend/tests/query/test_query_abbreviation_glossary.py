import json
from dataclasses import replace
from types import SimpleNamespace

from rag.abbreviations.adapters.memory import InMemoryAbbreviationRepository
from rag.abbreviations.service import AbbreviationGlossaryService
from rag.auth.abac import build_abac_filter
from rag.auth.context import UserContext
from rag.query.abbreviations import resolve_abbreviation_query
from rag.query.nodes.retrieval_nodes import _merge_abbreviation_glossary_hits
from rag.query.nodes.routing_nodes import RoutingNodes
from rag.query.qdrant import SearchHit
from rag.query.schemas import QueryRequest
from rag.query.state import initial_state


def test_authorized_glossary_expands_query_and_keeps_supporting_hit() -> None:
    service = _service_with_entry("AD", "Assistant Director")

    resolved, supporting_hits, attempted = resolve_abbreviation_query(
        _context("What approvals can the AD grant?"),
        service=service,
    )

    assert attempted is True
    assert resolved == "What approvals can the AD (Assistant Director) grant?"
    assert supporting_hits[0].payload["abbreviation_glossary_support"] is True
    assert supporting_hits[0].payload["doc_title"] == "Managed Abbreviation Glossary"


def test_full_definition_adds_abbreviation_for_retrieval() -> None:
    service = _service_with_entry("AD", "Assistant Director")

    resolved, supporting_hits, attempted = resolve_abbreviation_query(
        _context("What approvals can the Assistant Director grant?"),
        service=service,
    )

    assert attempted is True
    assert resolved == "What approvals can the Assistant Director (AD) grant?"
    assert supporting_hits[0].payload["text"] == "AD — Assistant Director"


def test_pdf_definition_cites_its_source_document_and_page() -> None:
    repository = InMemoryAbbreviationRepository()
    entry = repository.create_entry(
        abbreviation="AD",
        expansion="Assistant Director",
        actor_id="actor-1",
    )
    repository.entries[entry.id] = replace(
        entry,
        source_kind="pdf",
        source_document_id="document-1",
        source_document_title="Official Glossary.pdf",
        source_page=7,
    )

    _resolved, supporting_hits, _attempted = resolve_abbreviation_query(
        _context("What can AD approve?"),
        service=AbbreviationGlossaryService(repository),
    )

    assert supporting_hits[0].payload["doc_id"] == "document-1"
    assert supporting_hits[0].payload["doc_title"] == "Official Glossary.pdf"
    assert supporting_hits[0].payload["page"] == 7


def test_query_with_both_aliases_is_not_expanded_again() -> None:
    resolved, supporting_hits, attempted = resolve_abbreviation_query(
        _context("What approvals can AD (Assistant Director) grant?"),
        service=_service_with_entry("AD", "Assistant Director"),
    )

    assert attempted is True
    assert resolved == "What approvals can AD (Assistant Director) grant?"
    assert len(supporting_hits) == 1


def test_ambiguous_full_definition_is_not_rewritten() -> None:
    resolved, supporting_hits, attempted = resolve_abbreviation_query(
        _context("What approvals can the Assistant Director grant?"),
        service=_service_with_entries(
            ("AD", "Assistant Director"),
            ("ASD", "Assistant Director"),
        ),
    )

    assert attempted is False
    assert resolved == "What approvals can the Assistant Director grant?"
    assert supporting_hits == []


def test_longest_full_definition_wins_when_aliases_overlap() -> None:
    resolved, supporting_hits, attempted = resolve_abbreviation_query(
        _context("What approvals can the Assistant Director grant?"),
        service=_service_with_entries(
            ("AD", "Assistant Director"),
            ("DIR", "Director"),
        ),
    )

    assert attempted is True
    assert resolved == "What approvals can the Assistant Director (AD) grant?"
    assert [hit.payload["text"] for hit in supporting_hits] == [
        "AD — Assistant Director"
    ]


def test_glossary_is_global_across_query_spaces() -> None:
    resolved, supporting_hits, attempted = resolve_abbreviation_query(
        _context("What can the AD approve?", group_paths=("/finance",)),
        service=_service_with_entry("AD", "Assistant Director"),
    )

    assert attempted is True
    assert resolved == "What can the AD (Assistant Director) approve?"
    assert supporting_hits[0].payload["doc_id"] == "managed-glossary:global"


def test_raw_glossary_chunks_are_excluded_from_corpus_retrieval() -> None:
    ctx = _context("Show the glossary")
    raw_hit = SearchHit(
        point_id="raw-glossary-chunk",
        score=1.0,
        payload={
            "doc_id": "document-1",
            "doc_type": "abbreviation_glossary",
            "text": "AD — Assistant Director",
        },
    )

    assert _merge_abbreviation_glossary_hits(ctx, [raw_hit]) == []
    assert build_abac_filter(ctx["user"])["must_not"] == [
        {
            "key": "doc_type",
            "match": {"value": "abbreviation_glossary"},
        }
    ]


def test_capability_planner_uses_the_expanded_internal_query() -> None:
    class GlobalGraphPlanner:
        def verify_route(self, **_kwargs: object) -> str:
            return json.dumps(
                {
                    "capabilities": ["general_search", "global_graph"],
                    "response_mode": "explanation",
                    "scope": "corpus",
                    "coverage": "focused",
                    "temporal_scope": "current",
                }
            )

    node = SimpleNamespace(
        abbreviation_service=_service_with_entry(
            "AD", "Assistant Director"
        ),
        config=SimpleNamespace(rag_top_k=8),
        ollama=GlobalGraphPlanner(),
        routing_model="unused",
        reasoning_model="unused",
        query_planner_enabled=True,
    )
    ctx = _context(
        "What are the main themes involving Assistant Director across the corpus?"
    )

    RoutingNodes.intent_router(node, ctx)

    assert ctx["route_plan"].retrieval_strategy == "graphrag_global"
    assert ctx["route_plan"].resolved_query == (
        "What are the main themes involving Assistant Director (AD) across the corpus?"
    )
    assert ctx["route_plan"].original_query == (
        "What are the main themes involving Assistant Director across the corpus?"
    )


def test_lookup_failure_uses_original_query_and_marks_response_degraded() -> None:
    class FailingRepository(InMemoryAbbreviationRepository):
        def find_entries(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    node = SimpleNamespace(
        abbreviation_service=AbbreviationGlossaryService(FailingRepository()),
        config=SimpleNamespace(rag_top_k=8),
        ollama=None,
        routing_model="unused",
        reasoning_model="unused",
        query_planner_enabled=True,
    )
    ctx = _context("What can the AD approve?")

    RoutingNodes.intent_router(node, ctx)

    assert ctx["request"].query == "What can the AD approve?"
    assert ctx["degraded"] is True
    assert ctx["degraded_reason"] == "abbreviation_glossary_unavailable"


def _context(query: str, *, group_paths=("/legal",)):
    return initial_state(
        trace_id="trace-1",
        session_id="session-1",
        request=QueryRequest(query=query, group_path="/legal"),
        user=UserContext(
            user_id="user-1",
            email="user@example.test",
            group_paths=group_paths,
            clearance_level="NATO_RESTRICTED",
        ),
        started=0.0,
    )


def _service_with_entry(
    abbreviation: str,
    expansion: str,
) -> AbbreviationGlossaryService:
    return _service_with_entries((abbreviation, expansion))


def _service_with_entries(
    *entries: tuple[str, str],
) -> AbbreviationGlossaryService:
    repository = InMemoryAbbreviationRepository()
    for abbreviation, expansion in entries:
        repository.create_entry(
            abbreviation=abbreviation,
            expansion=expansion,
            actor_id="actor-1",
        )
    return AbbreviationGlossaryService(repository)
