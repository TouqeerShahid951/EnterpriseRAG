"""PostgreSQL claim and conflict repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from ..internal_schemas import ClaimRecord
from ...shared.contracts.evidence import ConflictPair, SourceAnchor
from ...shared.persistence import PostgresConnectionMixin
from ..claim_models import IngestClaimsResult

CONFLICT_LOOKUP_QUERY = """
SELECT ca.id claim_a_id, cb.id claim_b_id, ca.doc_id doc_a_id, cb.doc_id doc_b_id,
       ca.chunk_id chunk_a_id, cb.chunk_id chunk_b_id, ca.entity, ca.attribute,
       ca.value value_a, cb.value value_b, da.title doc_a_title, db.title doc_b_title,
       da.group_path group_a_path, db.group_path group_b_path,
       da.clearance_level group_a_clearance, db.clearance_level group_b_clearance,
       da.effective_date effective_date_a, db.effective_date effective_date_b
FROM conflicts c
JOIN claims ca ON ca.id = c.claim_a_id
JOIN claims cb ON cb.id = c.claim_b_id
JOIN documents da ON da.id = ca.doc_id
JOIN documents db ON db.id = cb.doc_id
WHERE c.status = 'open'
  AND da.deleted_at IS NULL
  AND db.deleted_at IS NULL
  AND ((%s::uuid IS NOT NULL AND (ca.id = %s::uuid OR cb.id = %s::uuid))
    OR (ca.doc_id = %s::uuid AND ca.chunk_id = %s AND ca.entity_norm = %s
        AND ca.attribute_norm = %s AND ca.value_norm = %s)
    OR (cb.doc_id = %s::uuid AND cb.chunk_id = %s AND cb.entity_norm = %s
        AND cb.attribute_norm = %s AND cb.value_norm = %s))
  AND (
    %s::text[] IS NULL
    OR (
      EXISTS (
        SELECT 1 FROM unnest(%s::text[]) AS visible(path)
        WHERE da.group_path = visible.path
      )
      AND EXISTS (
        SELECT 1 FROM unnest(%s::text[]) AS visible(path)
        WHERE db.group_path = visible.path
      )
    )
  )
"""


class PostgresClaimRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def save_claims(self, claims: list[ClaimRecord]) -> int:
        with self._connect() as conn:
            with conn.transaction():
                for claim in claims:
                    conn.execute(
                        """
                        INSERT INTO claims (id, doc_id, chunk_id, entity, attribute, value)
                        VALUES (COALESCE(%s::uuid, gen_random_uuid()), %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            chunk_id = EXCLUDED.chunk_id,
                            entity = EXCLUDED.entity,
                            attribute = EXCLUDED.attribute,
                            value = EXCLUDED.value
                        """,
                        (claim.id, claim.doc_id, claim.chunk_id, claim.entity, claim.attribute, claim.value),
                    )
        return len(claims)

    def save_claims_and_detect_conflicts(self, claims: list[ClaimRecord]) -> IngestClaimsResult:
        conflict_count = 0
        conflicted_claim_ids: set[str] = set()
        with self._connect() as conn:
            with conn.transaction():
                for claim in claims:
                    claim_id = _upsert_claim(conn, claim)
                    result = _insert_conflicts_for_claim(conn, claim_id, claim)
                    if result.rowcount:
                        conflict_count += result.rowcount
                        conflicted_claim_ids.add(claim_id)
        return IngestClaimsResult(
            saved_count=len(claims),
            conflict_count=conflict_count,
            conflicted_claim_ids=tuple(sorted(conflicted_claim_ids)),
        )

    def replace_claims_and_detect_conflicts(self, doc_id: str, claims: list[ClaimRecord]) -> IngestClaimsResult:
        with self._connect() as conn:
            with conn.transaction():
                return replace_claims_and_detect_conflicts_in_transaction(
                    conn, doc_id=doc_id, claims=claims
                )

    def lookup_claims(self, *, entity: str, attribute: str) -> list[ClaimRecord]:
        rows = self._execute_all(
            """
            SELECT id, doc_id, chunk_id, entity, attribute, value
            FROM claims
            WHERE entity_norm = %s AND attribute_norm = %s
            ORDER BY created_at DESC
            """,
            (_norm(entity), _norm(attribute)),
        )
        return [_claim_from_row(row) for row in rows]

    def list_claims_for_document(self, doc_id: str) -> list[ClaimRecord]:
        rows = self._execute_all(
            """
            SELECT id, doc_id, chunk_id, entity, attribute, value
            FROM claims
            WHERE doc_id = %s
            ORDER BY created_at ASC, id ASC
            """,
            (doc_id,),
        )
        return [_claim_from_row(row) for row in rows]

    def check_conflicts(
        self,
        claims: list[ClaimRecord],
        *,
        visible_group_paths: Sequence[str] | None = None,
    ) -> list[ConflictPair]:
        conflicts: dict[tuple[str, str], ConflictPair] = {}
        for claim in claims:
            for row in self._matching_conflict_rows(claim, visible_group_paths=visible_group_paths):
                pair = _conflict_from_row(row)
                conflicts[(pair.claim_a_id, pair.claim_b_id)] = pair
        return list(conflicts.values())

    def save_conflicts(self, conflicts: list[ConflictPair]) -> int:
        saved = 0
        with self._connect() as conn:
            with conn.transaction():
                for conflict in conflicts:
                    result = conn.execute(
                        """
                        INSERT INTO conflicts (claim_a_id, claim_b_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (conflict.claim_a_id, conflict.claim_b_id),
                    )
                    saved += result.rowcount
        return saved

    def _matching_conflict_rows(
        self,
        claim: ClaimRecord,
        *,
        visible_group_paths: Sequence[str] | None,
    ) -> list[dict[str, Any]]:
        claim_id = _uuid_or_none(claim.id)
        doc_id = _uuid_or_none(claim.doc_id)
        if claim_id is None and doc_id is None:
            return []
        return self._execute_all(
            CONFLICT_LOOKUP_QUERY,
            _conflict_params(claim, claim_id, doc_id, visible_group_paths),
        )


def replace_claims_and_detect_conflicts_in_transaction(
    conn: Any,
    *,
    doc_id: str,
    claims: list[ClaimRecord],
) -> IngestClaimsResult:
    """Replace one document's claims inside a caller-owned transaction."""
    conflict_count = 0
    conflicted_claim_ids: set[str] = set()
    normalized_claims = [claim.model_copy(update={"doc_id": doc_id}) for claim in claims]
    conn.execute("DELETE FROM claims WHERE doc_id = %s", (doc_id,))
    for claim in normalized_claims:
        claim_id = _upsert_claim(conn, claim)
        result = _insert_conflicts_for_claim(conn, claim_id, claim)
        if result.rowcount:
            conflict_count += result.rowcount
            conflicted_claim_ids.add(claim_id)
    return IngestClaimsResult(
        saved_count=len(normalized_claims),
        conflict_count=conflict_count,
        conflicted_claim_ids=tuple(sorted(conflicted_claim_ids)),
    )


def _upsert_claim(conn: Any, claim: ClaimRecord) -> str:
    row = conn.execute(
        """
        INSERT INTO claims (id, doc_id, chunk_id, entity, attribute, value)
        VALUES (COALESCE(%s::uuid, gen_random_uuid()), %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            doc_id = EXCLUDED.doc_id,
            chunk_id = EXCLUDED.chunk_id,
            entity = EXCLUDED.entity,
            attribute = EXCLUDED.attribute,
            value = EXCLUDED.value
        RETURNING id
        """,
        (claim.id, claim.doc_id, claim.chunk_id, claim.entity, claim.attribute, claim.value),
    ).fetchone()
    return str(row["id"])


def _insert_conflicts_for_claim(conn: Any, claim_id: str, claim: ClaimRecord) -> Any:
    return conn.execute(
        """
        INSERT INTO conflicts (claim_a_id, claim_b_id)
        SELECT existing.id, %s::uuid
        FROM claims existing
        WHERE existing.entity_norm = lower(btrim(%s))
          AND existing.attribute_norm = lower(btrim(%s))
          AND existing.value_norm <> lower(btrim(%s))
          AND existing.id <> %s::uuid
          AND existing.doc_id <> %s::uuid
        ON CONFLICT DO NOTHING
        """,
        (claim_id, claim.entity, claim.attribute, claim.value, claim_id, claim.doc_id),
    )


def _conflict_params(
    claim: ClaimRecord,
    claim_id: str | None,
    doc_id: str | None,
    visible_group_paths: Sequence[str] | None,
) -> tuple[Any, ...]:
    match_values = (doc_id, claim.chunk_id, _norm(claim.entity), _norm(claim.attribute), _norm(claim.value))
    visible = list(visible_group_paths) if visible_group_paths is not None else None
    return (claim_id, claim_id, claim_id, *match_values, *match_values, visible, visible, visible)


def _claim_from_row(row: dict[str, Any]) -> ClaimRecord:
    return ClaimRecord(
        id=str(row["id"]),
        doc_id=str(row["doc_id"]),
        chunk_id=str(row["chunk_id"]),
        entity=str(row["entity"]),
        attribute=str(row["attribute"]),
        value=str(row["value"]),
    )


def _conflict_from_row(row: dict[str, Any]) -> ConflictPair:
    return ConflictPair(
        claim_a_id=str(row["claim_a_id"]),
        claim_b_id=str(row["claim_b_id"]),
        doc_a_id=str(row["doc_a_id"]),
        doc_b_id=str(row["doc_b_id"]),
        chunk_a_id=str(row["chunk_a_id"]),
        chunk_b_id=str(row["chunk_b_id"]),
        entity=str(row["entity"]),
        attribute=str(row["attribute"]),
        value_a=str(row["value_a"]),
        value_b=str(row["value_b"]),
        effective_date_a=_date_str(row["effective_date_a"]),
        effective_date_b=_date_str(row["effective_date_b"]),
        source_a=_source(row, "a"),
        source_b=_source(row, "b"),
    )


def _source(row: dict[str, Any], side: str) -> SourceAnchor:
    return SourceAnchor(
        doc_id=str(row[f"doc_{side}_id"]),
        doc_title=str(row.get(f"doc_{side}_title") or "Untitled"),
        chunk_id=str(row[f"chunk_{side}_id"]),
        excerpt=f"{row['entity']} {row['attribute']}: {row[f'value_{side}']}",
        group_path=str(row.get(f"group_{side}_path") or "/"),
        clearance_level=str(row.get(f"group_{side}_clearance") or "NATO_RESTRICTED"),
        effective_date=_date_str(row.get(f"effective_date_{side}")),
    )


def _date_str(value: object) -> str | None:
    return value.isoformat() if isinstance(value, date) else None


def _uuid_or_none(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _norm(value: str) -> str:
    return value.strip().lower()
