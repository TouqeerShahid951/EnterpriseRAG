"""Normalize generated claims for backend persistence and Qdrant payloads."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from ..chunking import TextChunk
from ..messages import IngestJobPayload

ClaimPayload = dict[str, str]


def build_claim_records(
    *,
    job: IngestJobPayload,
    chunks: list[TextChunk],
    metadata: dict[str, object],
) -> list[ClaimPayload]:
    raw_claims = metadata.get("claims")
    if not isinstance(raw_claims, list) or not chunks:
        return []
    records: list[ClaimPayload] = []
    for index, raw_claim in enumerate(raw_claims):
        if not isinstance(raw_claim, dict):
            continue
        entity = _text(raw_claim.get("entity"))
        attribute = _text(raw_claim.get("attribute"))
        value = _text(raw_claim.get("value"))
        if not entity or not attribute or not value:
            continue
        chunk_id = _select_chunk_id(job.doc_id, chunks, entity, attribute, value)
        claim_id = str(uuid5(NAMESPACE_URL, f"{job.doc_id}:claim:{index}:{entity}:{attribute}:{value}"))
        records.append(
            {
                "id": claim_id,
                "doc_id": job.doc_id,
                "chunk_id": chunk_id,
                "entity": entity,
                "attribute": attribute,
                "value": value,
            }
        )
    return records


def claims_for_chunk(claims: list[ClaimPayload], chunk_id: str) -> list[ClaimPayload]:
    return [
        {
            "id": claim["id"],
            "entity": claim["entity"],
            "attribute": claim["attribute"],
            "value": claim["value"],
            "doc_id": claim["doc_id"],
            "chunk_id": claim["chunk_id"],
        }
        for claim in claims
        if claim["chunk_id"] == chunk_id
    ]


def claim_ids_for_chunk(claims: list[ClaimPayload], chunk_id: str) -> list[str]:
    return [claim["id"] for claim in claims if claim["chunk_id"] == chunk_id and claim.get("id")]


def _select_chunk_id(
    doc_id: str,
    chunks: list[TextChunk],
    entity: str,
    attribute: str,
    value: str,
) -> str:
    needles = [item.lower() for item in (value, entity, attribute) if item]
    for chunk in chunks:
        haystack = chunk.text.lower()
        if any(needle in haystack for needle in needles):
            return f"{doc_id}:{chunk.index}"
    return f"{doc_id}:{chunks[0].index}"


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
