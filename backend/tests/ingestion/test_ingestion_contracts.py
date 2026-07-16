from __future__ import annotations

from typing import Any

import pytest

from rag.ingestion.contracts import IngestJobPayload


def test_ingest_payload_round_trips_every_supported_wire_field() -> None:
    original = IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="minio://uploads/classified.pdf",
        group_path="/operations",
        effective_date="2026-07-01",
        supersedes=["doc-old"],
        acl_group_paths=["/operations", "/leadership"],
        doc_type="policy",
        clearance_level="COSMIC_TOP_SECRET",
        expiry_date="2027-07-01",
        description="Classified policy",
        content_type="application/pdf",
        quality_preset="high_accuracy",
        review_batch_id="review-1",
        image_review_batch_id="image-review-1",
        delivery_id="f7282b32-50db-4f3f-b99c-a242f777ce62",
    )

    serialized = original.to_dict()
    restored = IngestJobPayload.from_dict(serialized)

    assert restored == original
    assert serialized["supersedes"] is not original.supersedes
    assert serialized["acl_group_paths"] is not original.acl_group_paths


@pytest.mark.parametrize("field", ["job_id", "doc_id", "file_path", "group_path"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_ingest_payload_rejects_blank_required_fields(field: str, value: object) -> None:
    payload = _valid_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=field):
        IngestJobPayload.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("supersedes", "doc-old"), ("acl_group_paths", "/operations")],
)
def test_ingest_payload_rejects_non_list_collections(field: str, value: object) -> None:
    payload = _valid_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=field):
        IngestJobPayload.from_dict(payload)


def test_ingest_payload_rejects_unknown_clearance() -> None:
    payload = _valid_payload()
    payload["clearance_level"] = "UNKNOWN"

    with pytest.raises(ValueError, match="clearance_level"):
        IngestJobPayload.from_dict(payload)


def test_ingest_payload_rejects_invalid_delivery_id() -> None:
    payload = _valid_payload()
    payload["delivery_id"] = "not-a-uuid"

    with pytest.raises(ValueError, match="delivery_id"):
        IngestJobPayload.from_dict(payload)


def _valid_payload() -> dict[str, Any]:
    return {
        "job_id": "job-1",
        "doc_id": "doc-1",
        "file_path": "minio://uploads/document.pdf",
        "group_path": "/operations",
        "supersedes": [],
    }
