"""Small value objects shared by index publication steps."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True)
class IndexGeneration:
    id: str
    document_id: str
    job_id: str
    state: str
    expected_point_count: int
    expected_item_hash: str
    vector_dimension: int


def generation_id_for_job(job_id: str) -> str:
    """Keep retries on one isolated generation without another database round trip."""
    return str(uuid5(NAMESPACE_URL, f"document-index-generation:{job_id}"))


def aggregate_generation_hash(item_hashes: Iterable[str]) -> str:
    return sha256("\n".join(sorted(item_hashes)).encode("utf-8")).hexdigest()
