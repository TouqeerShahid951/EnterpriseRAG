"""Behavior and compatibility tests for shared evidence contracts."""

import pytest
from pydantic import ValidationError

from rag.query import schemas as query_schemas
from rag.shared.contracts.evidence import (
    ConflictPair,
    EvidenceField,
    EvidenceWindow,
    HighlightRange,
    SourceAnchor,
    SourceRegion,
)


@pytest.mark.parametrize(
    ("name", "canonical_contract"),
    (
        ("HighlightRange", HighlightRange),
        ("SourceRegion", SourceRegion),
        ("EvidenceField", EvidenceField),
        ("EvidenceWindow", EvidenceWindow),
        ("SourceAnchor", SourceAnchor),
        ("ConflictPair", ConflictPair),
    ),
)
def test_query_schema_facade_reexports_canonical_evidence_contracts(
    name: str,
    canonical_contract: type,
) -> None:
    assert getattr(query_schemas, name) is canonical_contract


def test_highlight_range_requires_a_nonempty_range() -> None:
    with pytest.raises(
        ValidationError, match="highlight range end must be greater than start"
    ):
        HighlightRange(start=2, end=2)


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"source_end": 2}, "evidence source end must be greater than start"),
        ({"quote_end": None}, "evidence quote offsets must be provided together"),
        ({"quote_start": 1}, "evidence quote must be contained by the source window"),
        (
            {"quote_start": 5, "quote_end": 5},
            "evidence quote end must be greater than start",
        ),
        (
            {"highlight_ranges": [HighlightRange(start=0, end=11)]},
            "evidence highlight must be contained by the passage",
        ),
    ),
)
def test_evidence_window_preserves_offset_invariants(
    updates: dict[str, object],
    message: str,
) -> None:
    payload: dict[str, object] = {
        "claim_id": "claim-1",
        "claim": "Supported claim",
        "passage": "0123456789",
        "support_status": "verified",
        "support_score": 1.0,
        "source_start": 2,
        "source_end": 8,
        "quote_start": 3,
        "quote_end": 5,
    }
    payload.update(updates)

    with pytest.raises(ValidationError, match=message):
        EvidenceWindow.model_validate(payload)


def test_source_anchor_keeps_attribution_fields_runtime_only() -> None:
    source = SourceAnchor(
        doc_id="doc-1",
        doc_title="Policy",
        chunk_id="chunk-1",
        excerpt="Status: approved",
        group_path="/ops",
        attribution_kind="table_row",
        attribution_table_title="Approvals",
        attribution_fields=[
            EvidenceField(label="Status", value="approved", supports_claim=True)
        ],
    )

    assert source.attribution_kind == "table_row"
    assert source.attribution_table_title == "Approvals"
    assert source.attribution_fields[0].supports_claim is True
    assert {
        "attribution_kind",
        "attribution_table_title",
        "attribution_fields",
    }.isdisjoint(source.model_dump())


def test_conflict_pair_keeps_nested_source_contracts() -> None:
    source = SourceAnchor(
        doc_id="doc-1",
        doc_title="Policy",
        chunk_id="chunk-1",
        excerpt="Status: approved",
        group_path="/ops",
    )

    conflict = ConflictPair(
        claim_a_id="claim-1",
        claim_b_id="claim-2",
        doc_a_id="doc-1",
        doc_b_id="doc-2",
        chunk_a_id="chunk-1",
        chunk_b_id="chunk-2",
        entity="request-1",
        attribute="status",
        value_a="approved",
        value_b="rejected",
        source_a=source,
        source_b=source.model_copy(update={"doc_id": "doc-2", "chunk_id": "chunk-2"}),
    )

    assert conflict.source_a is source
    assert conflict.source_b.doc_id == "doc-2"


def test_evidence_contracts_still_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HighlightRange.model_validate({"start": 0, "end": 1, "unknown": True})
