"""In-memory claim repository used by tests and local memory mode."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from ...auth.document_access import can_read_group_path
from ...schemas.internal import ClaimRecord
from ...schemas.query import ConflictPair, SourceAnchor
from ..claim_models import IngestClaimsResult


class InMemoryClaimRepository:
    def __init__(self) -> None:
        self.claims: dict[str, ClaimRecord] = {}
        self.conflicts: list[ConflictPair] = []

    def save_claims(self, claims: list[ClaimRecord]) -> int:
        for claim in claims:
            claim_id = claim.id or str(uuid4())
            self.claims[claim_id] = claim.model_copy(update={"id": claim_id})
        return len(claims)

    def save_claims_and_detect_conflicts(self, claims: list[ClaimRecord]) -> IngestClaimsResult:
        existing = list(self.claims.values())
        saved = self.save_claims(claims)
        conflicts: list[ConflictPair] = []
        conflicted_ids: set[str] = set()
        for claim in claims:
            saved_claim = self.claims.get(claim.id or "")
            if saved_claim is None:
                saved_claim = next(
                    (
                        candidate
                        for candidate in self.claims.values()
                        if _same_claim(candidate, claim)
                    ),
                    None,
                )
            if saved_claim is None or not saved_claim.id:
                continue
            for old in existing:
                if not old.id or old.doc_id == saved_claim.doc_id:
                    continue
                if _norm(old.entity) == _norm(saved_claim.entity) and _norm(old.attribute) == _norm(saved_claim.attribute) and _norm(old.value) != _norm(saved_claim.value):
                    conflicts.append(_conflict_pair(old, saved_claim))
                    conflicted_ids.add(saved_claim.id)
        conflict_count = self.save_conflicts(conflicts)
        return IngestClaimsResult(
            saved_count=saved,
            conflict_count=conflict_count,
            conflicted_claim_ids=tuple(sorted(conflicted_ids)),
        )

    def replace_claims_and_detect_conflicts(self, doc_id: str, claims: list[ClaimRecord]) -> IngestClaimsResult:
        self.claims = {
            claim_id: claim
            for claim_id, claim in self.claims.items()
            if claim.doc_id != doc_id
        }
        self.conflicts = [
            conflict
            for conflict in self.conflicts
            if conflict.doc_a_id != doc_id and conflict.doc_b_id != doc_id
        ]
        normalized_claims = [claim.model_copy(update={"doc_id": doc_id}) for claim in claims]
        return self.save_claims_and_detect_conflicts(normalized_claims)

    def lookup_claims(self, *, entity: str, attribute: str) -> list[ClaimRecord]:
        entity_norm = _norm(entity)
        attribute_norm = _norm(attribute)
        return [
            claim
            for claim in self.claims.values()
            if _norm(claim.entity) == entity_norm and _norm(claim.attribute) == attribute_norm
        ]

    def list_claims_for_document(self, doc_id: str) -> list[ClaimRecord]:
        return [
            claim
            for claim in self.claims.values()
            if claim.doc_id == doc_id
        ]

    def check_conflicts(
        self,
        claims: list[ClaimRecord],
        *,
        visible_group_paths: Sequence[str] | None = None,
    ) -> list[ConflictPair]:
        matches: list[ConflictPair] = []
        for conflict in self.conflicts:
            if (
                any(_matches_conflict(claim, conflict) for claim in claims)
                and _conflict_is_visible(conflict, visible_group_paths)
            ):
                matches.append(conflict)
        return matches

    def save_conflicts(self, conflicts: list[ConflictPair]) -> int:
        seen = {(item.claim_a_id, item.claim_b_id) for item in self.conflicts}
        saved = 0
        for conflict in conflicts:
            key = (conflict.claim_a_id, conflict.claim_b_id)
            reverse_key = (conflict.claim_b_id, conflict.claim_a_id)
            if key in seen or reverse_key in seen:
                continue
            self.conflicts.append(conflict)
            seen.add(key)
            saved += 1
        return saved


def _matches_conflict(claim: ClaimRecord, conflict: ConflictPair) -> bool:
    if claim.id and claim.id in {conflict.claim_a_id, conflict.claim_b_id}:
        return True
    claim_key = (
        claim.doc_id,
        claim.chunk_id,
        _norm(claim.entity),
        _norm(claim.attribute),
        _norm(claim.value),
    )
    return claim_key in {
        (
            conflict.doc_a_id,
            conflict.chunk_a_id,
            _norm(conflict.entity),
            _norm(conflict.attribute),
            _norm(conflict.value_a),
        ),
        (
            conflict.doc_b_id,
            conflict.chunk_b_id,
            _norm(conflict.entity),
            _norm(conflict.attribute),
            _norm(conflict.value_b),
        ),
    }


def _conflict_is_visible(conflict: ConflictPair, visible_group_paths: Sequence[str] | None) -> bool:
    if visible_group_paths is None:
        return True
    if conflict.source_a.group_path == "/" or conflict.source_b.group_path == "/":
        return True
    return (
        can_read_group_path(visible_group_paths, conflict.source_a.group_path)
        and can_read_group_path(visible_group_paths, conflict.source_b.group_path)
    )


def _norm(value: str) -> str:
    return value.strip().lower()


def _same_claim(left: ClaimRecord, right: ClaimRecord) -> bool:
    return (
        left.doc_id == right.doc_id
        and left.chunk_id == right.chunk_id
        and _norm(left.entity) == _norm(right.entity)
        and _norm(left.attribute) == _norm(right.attribute)
        and _norm(left.value) == _norm(right.value)
    )


def _conflict_pair(old: ClaimRecord, new: ClaimRecord) -> ConflictPair:
    source_a = _source_for_claim(old)
    source_b = _source_for_claim(new)
    return ConflictPair(
        claim_a_id=str(old.id),
        claim_b_id=str(new.id),
        doc_a_id=old.doc_id,
        doc_b_id=new.doc_id,
        chunk_a_id=old.chunk_id,
        chunk_b_id=new.chunk_id,
        entity=old.entity,
        attribute=old.attribute,
        value_a=old.value,
        value_b=new.value,
        source_a=source_a,
        source_b=source_b,
    )


def _source_for_claim(claim: ClaimRecord) -> SourceAnchor:
    return SourceAnchor(
        doc_id=claim.doc_id,
        doc_title=claim.doc_id,
        chunk_id=claim.chunk_id,
        excerpt=f"{claim.entity} {claim.attribute}: {claim.value}",
        group_path="/",
    )
