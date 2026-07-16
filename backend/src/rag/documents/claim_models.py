"""Claim and conflict repository contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .internal_schemas import ClaimRecord
from ..shared.contracts.evidence import ConflictPair


@dataclass(frozen=True)
class IngestClaimsResult:
    saved_count: int
    conflict_count: int
    conflicted_claim_ids: tuple[str, ...]


class ClaimRepository(Protocol):
    def save_claims(self, claims: list[ClaimRecord]) -> int: ...
    def save_claims_and_detect_conflicts(self, claims: list[ClaimRecord]) -> IngestClaimsResult: ...
    def replace_claims_and_detect_conflicts(self, doc_id: str, claims: list[ClaimRecord]) -> IngestClaimsResult: ...
    def list_claims_for_document(self, doc_id: str) -> list[ClaimRecord]: ...
    def lookup_claims(self, *, entity: str, attribute: str) -> list[ClaimRecord]: ...
    def check_conflicts(
        self,
        claims: list[ClaimRecord],
        *,
        visible_group_paths: Sequence[str] | None = None,
    ) -> list[ConflictPair]: ...
    def save_conflicts(self, conflicts: list[ConflictPair]) -> int: ...
