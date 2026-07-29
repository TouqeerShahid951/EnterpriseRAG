"""PostgreSQL persistence for the global abbreviation glossary."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from rag.shared.persistence import PostgresConnectionMixin

from ..ingestion import (
    remove_abbreviation_source_in_transaction,
    replace_abbreviation_glossary_in_transaction,
)
from ..models import (
    AbbreviationEntryRecord,
    AbbreviationGlossaryRecord,
    AbbreviationSourceRecord,
    DuplicateAbbreviationError,
    StaleAbbreviationRevisionError,
)


class PostgresAbbreviationRepository(PostgresConnectionMixin):
    def __init__(self, *, database_url: str) -> None:
        self.database_url = database_url

    def get_glossary(self) -> AbbreviationGlossaryRecord | None:
        sources = self.list_sources()
        if sources:
            latest = sources[0]
            return AbbreviationGlossaryRecord(
                source_document_id=latest.document_id,
                source_document_title=latest.document_title,
                updated_at=latest.activated_at,
            )
        row = self._execute_optional(
            "SELECT max(updated_at) AS updated_at FROM abbreviation_glossary_entries",
            (),
        )
        return (
            AbbreviationGlossaryRecord(None, None, row["updated_at"])
            if row and row.get("updated_at")
            else None
        )

    def list_sources(self) -> list[AbbreviationSourceRecord]:
        return [
            AbbreviationSourceRecord(
                document_id=str(row["document_id"]),
                document_title=str(row["document_title"]),
                entry_count=int(row["entry_count"]),
                activated_at=row.get("activated_at"),
            )
            for row in self._execute_all(
                """
                SELECT source.document_id::text AS document_id,
                       document.title AS document_title,
                       count(link.entry_id)::int AS entry_count,
                       source.activated_at
                FROM abbreviation_glossary_sources source
                JOIN documents document ON document.id = source.document_id
                LEFT JOIN abbreviation_glossary_entry_sources link
                    ON link.source_document_id = source.document_id
                WHERE document.deleted_at IS NULL AND document.is_current = TRUE
                GROUP BY source.document_id, document.title, source.activated_at
                ORDER BY source.activated_at DESC, document.title
                """
            )
        ]

    def list_entries(self) -> list[AbbreviationEntryRecord]:
        return [
            _entry_from_row(row)
            for row in self._execute_all(f"{_ENTRY_SELECT} ORDER BY entry.abbreviation")
        ]

    def get_entry(self, entry_id: str) -> AbbreviationEntryRecord | None:
        row = self._execute_optional(
            f"{_ENTRY_SELECT} WHERE entry.id = %s::uuid",
            (entry_id,),
        )
        return _entry_from_row(row) if row else None

    def create_entry(
        self,
        *,
        abbreviation: str,
        expansion: str,
        actor_id: str,
    ) -> AbbreviationEntryRecord:
        with self._connect() as conn:
            inserted = conn.execute(
                """
                INSERT INTO abbreviation_glossary_entries
                    (abbreviation, expansion, source_kind, created_by, updated_by)
                VALUES (%s, %s, 'ui', %s::uuid, %s::uuid)
                ON CONFLICT DO NOTHING
                RETURNING id::text AS id
                """,
                (abbreviation, expansion, actor_id, actor_id),
            ).fetchone()
            if inserted is None:
                raise DuplicateAbbreviationError(abbreviation)
            self._audit(
                conn,
                event_type="abbreviation.created",
                actor_id=actor_id,
                entry_id=str(inserted["id"]),
                payload={"abbreviation": abbreviation, "source_kind": "ui"},
            )
        created = self.get_entry(str(inserted["id"]))
        if created is None:
            raise RuntimeError("created abbreviation entry could not be read")
        return created

    def update_entry(
        self,
        entry_id: str,
        *,
        abbreviation: str,
        expansion: str,
        expected_revision: int,
        actor_id: str,
    ) -> AbbreviationEntryRecord | None:
        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT id::text AS id, abbreviation, revision
                FROM abbreviation_glossary_entries
                WHERE id = %s::uuid
                FOR UPDATE
                """,
                (entry_id,),
            ).fetchone()
            if current is None:
                return None
            if int(current["revision"]) != expected_revision:
                raise StaleAbbreviationRevisionError(entry_id)
            duplicate = conn.execute(
                """
                SELECT 1 FROM abbreviation_glossary_entries
                WHERE upper(abbreviation) = upper(%s) AND id <> %s::uuid
                """,
                (abbreviation, entry_id),
            ).fetchone()
            if duplicate is not None:
                raise DuplicateAbbreviationError(abbreviation)
            conn.execute(
                """
                UPDATE abbreviation_glossary_entries
                SET abbreviation = %s, expansion = %s, source_kind = 'ui',
                    source_document_id = NULL, source_page = NULL,
                    revision = revision + 1,
                    updated_by = %s::uuid, updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (abbreviation, expansion, actor_id, entry_id),
            )
            conn.execute(
                "DELETE FROM abbreviation_glossary_entry_sources WHERE entry_id = %s::uuid",
                (entry_id,),
            )
            self._audit(
                conn,
                event_type="abbreviation.updated",
                actor_id=actor_id,
                entry_id=entry_id,
                payload={
                    "abbreviation": abbreviation,
                    "previous_abbreviation": str(current["abbreviation"]),
                    "source_kind": "ui",
                },
            )
        return self.get_entry(entry_id)

    def delete_entry(
        self,
        entry_id: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> bool:
        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT abbreviation, revision
                FROM abbreviation_glossary_entries
                WHERE id = %s::uuid
                FOR UPDATE
                """,
                (entry_id,),
            ).fetchone()
            if current is None:
                return False
            if int(current["revision"]) != expected_revision:
                raise StaleAbbreviationRevisionError(entry_id)
            conn.execute(
                "DELETE FROM abbreviation_glossary_entries WHERE id = %s::uuid",
                (entry_id,),
            )
            self._audit(
                conn,
                event_type="abbreviation.deleted",
                actor_id=actor_id,
                entry_id=entry_id,
                payload={"abbreviation": str(current["abbreviation"])},
            )
        return True

    def remove_source(self, document_id: str, *, actor_id: str) -> bool:
        with self._connect() as conn:
            return remove_abbreviation_source_in_transaction(
                conn,
                document_id=document_id,
                actor_id=actor_id,
            )

    def replace_from_document(
        self,
        *,
        document_id: str,
        entries: Sequence[tuple[str, str, int | None]],
    ) -> int:
        with self._connect() as conn:
            return replace_abbreviation_glossary_in_transaction(
                conn,
                document_id=document_id,
                entries=entries,
            )

    def find_entries(
        self,
        abbreviations: Sequence[str],
        *,
        query: str,
    ) -> list[AbbreviationEntryRecord]:
        if not abbreviations and not query:
            return []
        rows = self._execute_all(
            f"""
            {_ENTRY_SELECT}
            WHERE upper(entry.abbreviation) = ANY(%s::text[])
               OR strpos(lower(%s), lower(entry.expansion)) > 0
            ORDER BY entry.abbreviation
            """,
            ([value.upper() for value in abbreviations], query),
        )
        return [_entry_from_row(row) for row in rows]

    @staticmethod
    def _audit(
        conn,
        *,
        event_type: str,
        actor_id: str | None,
        entry_id: str,
        payload: dict[str, object],
        target_type: str = "abbreviation",
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
            VALUES (%s, %s::uuid, %s, %s, %s::jsonb)
            """,
            (event_type, actor_id, target_type, entry_id, json.dumps(payload)),
        )


_ENTRY_SELECT = """
    SELECT entry.id::text AS id, entry.abbreviation, entry.expansion,
           entry.source_kind, entry.source_document_id::text AS source_document_id,
           document.title AS source_document_title, entry.source_page, entry.revision,
           (SELECT count(*) FROM abbreviation_glossary_entry_sources source
            WHERE source.entry_id = entry.id)::int AS source_count,
           entry.created_at, entry.updated_at
    FROM abbreviation_glossary_entries entry
    LEFT JOIN documents document ON document.id = entry.source_document_id
"""


def _entry_from_row(row: dict[str, Any]) -> AbbreviationEntryRecord:
    return AbbreviationEntryRecord(
        id=str(row["id"]),
        abbreviation=str(row["abbreviation"]),
        expansion=str(row["expansion"]),
        source_kind=str(row["source_kind"]),
        source_document_id=str(row["source_document_id"])
        if row.get("source_document_id")
        else None,
        source_document_title=str(row["source_document_title"])
        if row.get("source_document_title")
        else None,
        source_page=int(row["source_page"]) if row.get("source_page") else None,
        source_count=int(row.get("source_count") or 0),
        revision=int(row["revision"]),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )
