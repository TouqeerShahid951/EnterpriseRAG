"""Document-owned writes that must join an ingestion publication transaction."""

from __future__ import annotations

import json
from typing import Any

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE
from rag.documents.adapters.claim_postgres import (
    replace_claims_and_detect_conflicts_in_transaction,
)
from rag.documents.adapters.postgres import validate_edges
from rag.documents.internal_schemas import ClaimRecord


def apply_staged_ingestion_data(
    conn: Any,
    *,
    document_id: str,
    metadata: dict[str, Any],
    claims: list[dict[str, Any]],
    supersedes: list[str],
) -> None:
    """Apply document-derived data in the caller's publication transaction."""
    _apply_metadata(conn, document_id=document_id, metadata=metadata)
    replace_claims_and_detect_conflicts_in_transaction(
        conn,
        doc_id=document_id,
        claims=[
            ClaimRecord.model_validate(claim).model_copy(update={"doc_id": document_id})
            for claim in claims
        ],
    )
    _apply_supersession(conn, new_document_id=document_id, supersedes=supersedes)


def _apply_metadata(conn: Any, *, document_id: str, metadata: dict[str, Any]) -> None:
    flags = _object(metadata.get("metadata_flags"))
    version = metadata.get("metadata_version")
    if isinstance(version, int) and version > 0:
        flags["metadata_version"] = version
    confidence = _object(metadata.get("metadata_confidence"))
    if confidence:
        flags["metadata_confidence"] = confidence
    provenance = _object(metadata.get("metadata_provenance"))
    if provenance:
        flags["metadata_provenance"] = provenance
    row = conn.execute(
        """
        UPDATE documents
        SET summary = %s,
            language = %s,
            topics = %s::jsonb,
            llm_topics = %s::jsonb,
            doc_type = CASE WHEN doc_type = %s THEN doc_type ELSE COALESCE(%s, doc_type) END,
            auto_doc_type = %s,
            extracted_dates = %s::jsonb,
            metadata_flags = %s::jsonb,
            updated_at = NOW()
        WHERE id = %s AND deleted_at IS NULL
        RETURNING id
        """,
        (
            _text_or_none(metadata.get("summary")),
            _text_or_none(metadata.get("language")),
            json.dumps(_string_list(metadata.get("topics"))),
            json.dumps(_string_list(metadata.get("llm_topics"))),
            ABBREVIATION_GLOSSARY_DOC_TYPE,
            _derived_doc_type(metadata),
            _text_or_none(metadata.get("auto_doc_type")),
            json.dumps(_object(metadata.get("extracted_dates"))),
            json.dumps(flags),
            document_id,
        ),
    ).fetchone()
    if row is None:
        raise ValueError("document does not exist")
    conn.execute("DELETE FROM document_entities WHERE doc_id = %s", (document_id,))
    for entity in _list_of_objects(metadata.get("named_entities")):
        text = _text_or_none(entity.get("text"))
        entity_type = _text_or_none(entity.get("type"))
        if text and entity_type:
            conn.execute(
                """
                INSERT INTO document_entities (doc_id, text, entity_type, start_offset, end_offset)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    document_id,
                    text,
                    entity_type,
                    _nonnegative_int(entity.get("start")),
                    _nonnegative_int(entity.get("end")),
                ),
            )
    conn.execute("DELETE FROM document_cross_references WHERE doc_id = %s", (document_id,))
    for reference in _list_of_objects(metadata.get("cross_references")):
        ref_text = _text_or_none(reference.get("ref_text") or reference.get("text"))
        ref_type = _text_or_none(reference.get("ref_type") or reference.get("type"))
        if ref_text and ref_type:
            conn.execute(
                """
                INSERT INTO document_cross_references (doc_id, ref_text, ref_type, position)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    document_id,
                    ref_text,
                    ref_type,
                    _nonnegative_int(reference.get("position")),
                ),
            )


def _apply_supersession(conn: Any, *, new_document_id: str, supersedes: list[str]) -> None:
    if not supersedes:
        return
    validate_edges(conn, new_document_id, supersedes)
    for old_document_id in supersedes:
        conn.execute(
            """
            INSERT INTO supersession_edges (old_doc_id, new_doc_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (old_document_id, new_document_id),
        )
        conn.execute(
            """
            UPDATE documents
            SET is_current = FALSE, superseded_by = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (new_document_id, old_document_id),
        )


def _object(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_objects(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := str(item).strip())))


def _text_or_none(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _derived_doc_type(metadata: dict[str, Any]) -> str | None:
    return _text_or_none(metadata.get("doc_type")) or _text_or_none(metadata.get("auto_doc_type"))


def _nonnegative_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) and value >= 0 else None
