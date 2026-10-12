from __future__ import annotations

import json

from rag.query.sources.database_router import route_database_source
from rag.query.sources.source_catalog import VisibleQuerySource


class RouterClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def generate_json(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return json.dumps(self.payload)


def test_router_selects_only_source_without_model() -> None:
    source = _source("orders", domains=["sales"])

    decision = route_database_source(
        "Show open orders",
        [source],
        client=None,
        model=None,
    )

    assert decision.outcome == "selected"
    assert decision.selected_catalog_id == "orders"
    assert decision.router_mode == "deterministic"


def test_router_uses_configured_model_for_ambiguous_shortlist() -> None:
    client = RouterClient(
        {
            "outcome": "selected",
            "catalog_id": "orders",
            "candidate_catalog_ids": ["orders"],
            "reason": "The question asks about orders.",
        }
    )

    decision = route_database_source(
        "Show current activity",
        [_source("orders", domains=["sales"]), _source("people", domains=["hr"])],
        client=client,
        model="configured-router",
    )

    assert decision.selected_catalog_id == "orders"
    assert decision.router_mode == "ai_assisted"
    assert client.calls[0]["model"] == "configured-router"


def test_router_requests_clarification_instead_of_guessing_or_fanout() -> None:
    client = RouterClient(
        {
            "outcome": "clarification",
            "candidate_catalog_ids": ["orders", "archive"],
            "reason": "Both catalogs contain orders.",
            "clarification_question": "Do you mean current or archived orders?",
        }
    )

    decision = route_database_source(
        "Show order totals",
        [_source("orders"), _source("archive")],
        client=client,
        model="configured-router",
    )

    assert decision.outcome == "clarification"
    assert decision.selected_catalog_id is None
    assert [candidate.catalog_id for candidate in decision.candidates] == [
        "orders",
        "archive",
    ]


def test_router_rejects_model_catalog_outside_authorized_shortlist() -> None:
    client = RouterClient(
        {
            "outcome": "selected",
            "catalog_id": "secret",
            "reason": "Use an unavailable source.",
        }
    )

    decision = route_database_source(
        "Show current activity",
        [_source("orders"), _source("people")],
        client=client,
        model="configured-router",
    )

    assert decision.outcome == "clarification"
    assert decision.selected_catalog_id is None
    assert all(candidate.catalog_id != "secret" for candidate in decision.candidates)


def _source(
    catalog_id: str,
    *,
    domains: list[str] | None = None,
) -> VisibleQuerySource:
    return VisibleQuerySource(
        id=f"connector_catalog:{catalog_id}",
        target_kind="catalog",
        target_id=catalog_id,
        name=catalog_id.title(),
        description=f"Approved {catalog_id} database",
        connector_type="fake",
        scope="database_scope",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        match_text=catalog_id,
        routing_card={
            "domains": domains or [],
            "entities": [],
            "metrics": [],
            "synonyms": [],
            "example_questions": [],
            "exclusions": [],
        },
    )
