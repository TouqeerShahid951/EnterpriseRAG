"""Atomic glossary replacement inside an ingestion publication transaction."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from rag.shared.contracts.abbreviations import normalize_abbreviation_entry

from .models import SourceAbbreviationConflictError


def replace_abbreviation_glossary_in_transaction(
    conn: Any,
    *,
    document_id: str,
    entries: Sequence[tuple[str, str, int | None]],
) -> int:
    normalized: dict[str, tuple[str, int | None]] = {}
    for raw_abbreviation, raw_expansion, source_page in entries:
        abbreviation, expansion = normalize_abbreviation_entry(
            raw_abbreviation, raw_expansion
        )
        if source_page is not None and (
            not isinstance(source_page, int) or isinstance(source_page, bool) or source_page < 1
        ):
            raise ValueError("abbreviation source page must be a positive integer")
        current = normalized.get(abbreviation)
        if current is not None and current[0].casefold() != expansion.casefold():
            raise ValueError(f"conflicting definitions for {abbreviation}")
        normalized.setdefault(abbreviation, (expansion, source_page))
    if not normalized:
        raise ValueError("abbreviation glossary contains no usable entries")

    conn.execute("SELECT pg_advisory_xact_lock(hashtext('abbreviation_glossary_sources'))")
    document = conn.execute(
        """
        SELECT id::text AS id, uploaded_by::text AS uploaded_by
        FROM documents
        WHERE id = %s::uuid AND deleted_at IS NULL
          AND doc_type = 'abbreviation_glossary'
        FOR UPDATE
        """,
        (document_id,),
    ).fetchone()
    if document is None:
        raise ValueError("abbreviation glossary document was not found")

    superseded_source_ids = [
        str(row["document_id"])
        for row in conn.execute(
            """
            SELECT edge.old_doc_id::text AS document_id
            FROM supersession_edges edge
            JOIN documents old_document ON old_document.id = edge.old_doc_id
            WHERE edge.new_doc_id = %s::uuid
              AND old_document.doc_type = 'abbreviation_glossary'
            """,
            (document_id,),
        ).fetchall()
    ]
    for source_document_id in [document_id, *superseded_source_ids]:
        conn.execute(
            "DELETE FROM abbreviation_glossary_sources WHERE document_id = %s::uuid",
            (source_document_id,),
        )
    _prune_orphaned_pdf_entries(conn)
    conn.execute(
        """
        INSERT INTO abbreviation_glossary_sources (document_id)
        VALUES (%s::uuid)
        ON CONFLICT (document_id) DO UPDATE SET activated_at = NOW()
        """,
        (document_id,),
    )
    for abbreviation, (expansion, source_page) in normalized.items():
        existing = conn.execute(
            """
            SELECT id::text AS id, expansion, source_kind
            FROM abbreviation_glossary_entries
            WHERE upper(abbreviation) = upper(%s)
            FOR UPDATE
            """,
            (abbreviation,),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["source_kind"]) != "pdf"
                or str(existing["expansion"]).casefold() != expansion.casefold()
            ):
                raise SourceAbbreviationConflictError(
                    f"active glossary contains a conflicting definition for {abbreviation}"
                )
            entry_id = str(existing["id"])
        else:
            inserted = conn.execute(
                """
                INSERT INTO abbreviation_glossary_entries
                    (abbreviation, expansion, source_kind, source_document_id,
                     source_page, created_by, updated_by)
                VALUES (%s, %s, 'pdf', %s::uuid, %s, %s::uuid, %s::uuid)
                RETURNING id::text AS id
                """,
                (
                    abbreviation,
                    expansion,
                    document_id,
                    source_page,
                    document["uploaded_by"],
                    document["uploaded_by"],
                ),
            ).fetchone()
            entry_id = str(inserted["id"])
        conn.execute(
            """
            INSERT INTO abbreviation_glossary_entry_sources
                (entry_id, source_document_id, source_page)
            VALUES (%s::uuid, %s::uuid, %s)
            ON CONFLICT (entry_id, source_document_id)
            DO UPDATE SET source_page = EXCLUDED.source_page
            """,
            (entry_id, document_id, source_page),
        )
    _refresh_pdf_entry_provenance(conn)
    conn.execute(
        """
        INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
        VALUES ('abbreviation.imported', %s::uuid, 'document', %s, %s::jsonb)
        """,
        (
            document["uploaded_by"],
            document_id,
            json.dumps(
                {
                    "document_id": document_id,
                    "entry_count": len(normalized),
                    "superseded_source_ids": superseded_source_ids,
                }
            ),
        ),
    )
    return len(normalized)


def remove_abbreviation_source_in_transaction(
    conn: Any,
    *,
    document_id: str,
    actor_id: str,
) -> bool:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('abbreviation_glossary_sources'))")
    removed = conn.execute(
        """
        DELETE FROM abbreviation_glossary_sources
        WHERE document_id = %s::uuid
        RETURNING document_id
        """,
        (document_id,),
    ).fetchone()
    if removed is None:
        return False
    _prune_orphaned_pdf_entries(conn)
    _refresh_pdf_entry_provenance(conn)
    conn.execute(
        """
        UPDATE documents
        SET is_current = FALSE, updated_at = NOW()
        WHERE id = %s::uuid AND doc_type = 'abbreviation_glossary'
        """,
        (document_id,),
    )
    conn.execute(
        """
        INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
        VALUES ('abbreviation.source_removed', %s::uuid, 'document', %s, %s::jsonb)
        """,
        (actor_id, document_id, json.dumps({"document_id": document_id})),
    )
    return True


def _prune_orphaned_pdf_entries(conn: Any) -> None:
    conn.execute(
        """
        DELETE FROM abbreviation_glossary_entries entry
        WHERE entry.source_kind = 'pdf'
          AND NOT EXISTS (
              SELECT 1
              FROM abbreviation_glossary_entry_sources source
              WHERE source.entry_id = entry.id
          )
        """
    )


def _refresh_pdf_entry_provenance(conn: Any) -> None:
    conn.execute(
        """
        UPDATE abbreviation_glossary_entries entry
        SET source_document_id = (
                SELECT link.source_document_id
                FROM abbreviation_glossary_entry_sources link
                WHERE link.entry_id = entry.id
                ORDER BY link.source_document_id
                LIMIT 1
            ),
            source_page = (
                SELECT link.source_page
                FROM abbreviation_glossary_entry_sources link
                WHERE link.entry_id = entry.id
                ORDER BY link.source_document_id
                LIMIT 1
            ),
            updated_at = NOW()
        WHERE entry.source_kind = 'pdf'
        """
    )
