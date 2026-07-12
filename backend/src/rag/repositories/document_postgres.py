"""PostgreSQL document repository."""

from __future__ import annotations

import json
from typing import Any, Literal

from ..auth.abac import normalize_group_path
from ..shared.contracts.clearance import ClearanceLevel, normalize_clearance_level
from .audit_models import audit_event_from_row
from .document_models import (
    AuditEventRecord,
    DocumentCrossReferenceRecord,
    DocumentEntityRecord,
    DocumentImageAssetRecord,
    DocumentRecord,
)
from .human_review_postgres import (
    review_batch_from_row as review_batch_from_row,
    review_item_from_row as review_item_from_row,
)
from .image_review_postgres import (
    image_review_batch_from_row as image_review_batch_from_row,
    image_review_candidate_from_row as image_review_candidate_from_row,
)
from .postgres import PostgresConnectionMixin


class PostgresDocumentRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create_document(self, **kwargs: Any) -> DocumentRecord:
        row = self._execute_one(
            """
            INSERT INTO documents (
                id, title, source_id, group_path, clearance_level, doc_type, effective_date, expiry_date, description,
                uploaded_by, file_path, content_hash, pending_supersedes, ingest_status
            )
            VALUES (COALESCE(%s::uuid, gen_random_uuid()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING *
            """,
            (
                kwargs.get("document_id"),
                kwargs["title"],
                kwargs["source_id"].strip(),
                normalize_group_path(kwargs["group_path"]),
                normalize_clearance_level(kwargs.get("clearance_level")),
                kwargs["doc_type"],
                kwargs["effective_date"],
                kwargs.get("expiry_date"),
                kwargs.get("description"),
                kwargs["uploaded_by"],
                kwargs["file_path"],
                kwargs["content_hash"],
                json.dumps(kwargs["pending_supersedes"]),
                kwargs["ingest_status"],
            ),
        )
        return document_from_row(row)

    def list_documents(self, *, state: Literal["active", "deleted"] = "active") -> list[DocumentRecord]:
        if state not in {"active", "deleted"}:
            raise ValueError("document state must be active or deleted")
        deleted_clause = "d.deleted_at IS NULL" if state == "active" else "d.deleted_at IS NOT NULL"
        rows = self._execute_all(
            f"""
            SELECT d.*, COALESCE(shares.shared_group_paths, '[]'::jsonb) AS shared_group_paths
            FROM documents d
            LEFT JOIN (
                SELECT document_id, jsonb_agg(group_path ORDER BY group_path) AS shared_group_paths
                FROM document_shares
                GROUP BY document_id
            ) shares ON shares.document_id = d.id
            WHERE {deleted_clause}
            ORDER BY d.created_at DESC
            """
        )
        return [document_from_row(row) for row in rows]

    def get_document(self, document_id: str, *, include_deleted: bool = False) -> DocumentRecord | None:
        deleted_clause = "" if include_deleted else "AND d.deleted_at IS NULL"
        row = self._execute_optional(
            f"""
            SELECT d.*, COALESCE(shares.shared_group_paths, '[]'::jsonb) AS shared_group_paths
            FROM documents d
            LEFT JOIN (
                SELECT document_id, jsonb_agg(group_path ORDER BY group_path) AS shared_group_paths
                FROM document_shares
                GROUP BY document_id
            ) shares ON shares.document_id = d.id
            WHERE d.id = %s {deleted_clause}
            """,
            (document_id,),
        )
        return document_from_row(row) if row else None

    def replace_document_shares(
        self,
        document_id: str,
        *,
        group_paths: list[str],
        actor_id: str | None,
    ) -> DocumentRecord | None:
        normalized = _unique_text([normalize_group_path(path) for path in group_paths])
        with self._connect() as conn:
            with conn.transaction():
                document = conn.execute(
                    "SELECT id::text, group_path FROM documents WHERE id = %s",
                    (document_id,),
                ).fetchone()
                if document is None:
                    return None
                owner_group_path = normalize_group_path(str(document["group_path"]))
                shares = [path for path in normalized if path != owner_group_path]
                conn.execute("DELETE FROM document_shares WHERE document_id = %s", (document_id,))
                for group_path in shares:
                    conn.execute(
                        """
                        INSERT INTO document_shares (document_id, group_path, created_by)
                        VALUES (%s, %s, %s)
                        """,
                        (document_id, group_path, actor_id),
                    )
                conn.execute("UPDATE documents SET updated_at = NOW() WHERE id = %s", (document_id,))
        return self.get_document(document_id, include_deleted=True)

    def replace_document_access_scope(
        self,
        document_id: str,
        *,
        owner_group_path: str,
        shared_group_paths: list[str],
        actor_id: str | None,
    ) -> DocumentRecord | None:
        owner_group = normalize_group_path(owner_group_path)
        shares = [path for path in _unique_text([normalize_group_path(path) for path in shared_group_paths]) if path != owner_group]
        with self._connect() as conn:
            with conn.transaction():
                document = conn.execute("SELECT id::text FROM documents WHERE id = %s", (document_id,)).fetchone()
                if document is None:
                    return None
                conn.execute(
                    """
                    UPDATE documents
                    SET group_path = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (owner_group, document_id),
                )
                conn.execute("DELETE FROM document_shares WHERE document_id = %s", (document_id,))
                for group_path in shares:
                    conn.execute(
                        """
                        INSERT INTO document_shares (document_id, group_path, created_by)
                        VALUES (%s, %s, %s)
                        """,
                        (document_id, group_path, actor_id),
                    )
        return self.get_document(document_id, include_deleted=True)

    def update_document_clearance(self, document_id: str, clearance_level: ClearanceLevel) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents
            SET clearance_level = %s,
                updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (normalize_clearance_level(clearance_level), document_id),
        )
        return document_from_row(row) if row else None

    def update_document_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
    ) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents
            SET topics = %s::jsonb,
                llm_topics = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (
                json.dumps(_unique_text(topics)),
                json.dumps(_unique_text(llm_topics)),
                document_id,
            ),
        )
        return document_from_row(row) if row else None

    def save_document_metadata(
        self,
        *,
        document_id: str,
        summary: str | None,
        language: str | None,
        topics: list[str],
        llm_topics: list[str],
        doc_type: str | None = None,
        auto_doc_type: str | None,
        extracted_dates: dict[str, Any],
        metadata_flags: dict[str, Any],
        entities: list[DocumentEntityRecord],
        cross_references: list[DocumentCrossReferenceRecord],
    ) -> DocumentRecord | None:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    UPDATE documents
                    SET summary = %s,
                        language = %s,
                        topics = %s::jsonb,
                        llm_topics = %s::jsonb,
                        doc_type = COALESCE(%s, doc_type),
                        auto_doc_type = %s,
                        extracted_dates = %s::jsonb,
                        metadata_flags = %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (
                        summary,
                        language,
                        json.dumps(_unique_text(topics)),
                        json.dumps(_unique_text(llm_topics)),
                        doc_type,
                        auto_doc_type,
                        json.dumps(extracted_dates),
                        json.dumps(metadata_flags),
                        document_id,
                    ),
                ).fetchone()
                if row is None:
                    return None
                conn.execute("DELETE FROM document_entities WHERE doc_id = %s", (document_id,))
                for entity in entities:
                    conn.execute(
                        """
                        INSERT INTO document_entities (doc_id, text, entity_type, start_offset, end_offset)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (document_id, entity.text, entity.type, entity.start, entity.end),
                    )
                conn.execute("DELETE FROM document_cross_references WHERE doc_id = %s", (document_id,))
                for ref in cross_references:
                    conn.execute(
                        """
                        INSERT INTO document_cross_references (doc_id, ref_text, ref_type, position)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (document_id, ref.ref_text, ref.ref_type, ref.position),
                    )
        return document_from_row(row)

    def list_document_entities(self, document_id: str) -> list[DocumentEntityRecord]:
        rows = self._execute_all(
            """
            SELECT doc_id, text, entity_type, start_offset, end_offset
            FROM document_entities
            WHERE doc_id = %s
            ORDER BY COALESCE(start_offset, 2147483647), lower(text), entity_type
            """,
            (document_id,),
        )
        return [
            DocumentEntityRecord(
                doc_id=str(row["doc_id"]),
                text=str(row["text"]),
                type=str(row["entity_type"]),
                start=row.get("start_offset"),
                end=row.get("end_offset"),
            )
            for row in rows
        ]

    def list_document_cross_references(self, document_id: str) -> list[DocumentCrossReferenceRecord]:
        rows = self._execute_all(
            """
            SELECT doc_id, ref_text, ref_type, position
            FROM document_cross_references
            WHERE doc_id = %s
            ORDER BY COALESCE(position, 2147483647), lower(ref_text), ref_type
            """,
            (document_id,),
        )
        return [
            DocumentCrossReferenceRecord(
                doc_id=str(row["doc_id"]),
                ref_text=str(row["ref_text"]),
                ref_type=str(row["ref_type"]),
                position=row.get("position"),
            )
            for row in rows
        ]

    def find_current_by_content_hash(self, content_hash: str) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            SELECT * FROM documents
            WHERE content_hash = %s AND deleted_at IS NULL AND is_current = TRUE
            ORDER BY created_at DESC LIMIT 1
            """,
            (content_hash,),
        )
        return document_from_row(row) if row else None

    def soft_delete_document(self, document_id: str) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents
            SET deleted_at = COALESCE(deleted_at, NOW()), is_current = FALSE, updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL RETURNING *
            """,
            (document_id,),
        )
        return document_from_row(row) if row else None

    def restore_document(self, document_id: str) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents d
            SET deleted_at = NULL,
                is_current = NOT EXISTS (
                    SELECT 1 FROM supersession_edges e WHERE e.old_doc_id = d.id
                ),
                updated_at = NOW()
            WHERE d.id = %s AND d.deleted_at IS NOT NULL
            RETURNING *
            """,
            (document_id,),
        )
        return document_from_row(row) if row else None

    def permanently_delete_document(self, document_id: str) -> DocumentRecord | None:
        row = self._execute_optional(
            "DELETE FROM documents WHERE id = %s RETURNING *",
            (document_id,),
        )
        return document_from_row(row) if row else None

    def mark_superseded(self, *, new_doc_id: str, old_doc_ids: list[str]) -> list[DocumentRecord]:
        with self._connect() as conn:
            with conn.transaction():
                validate_edges(conn, new_doc_id, old_doc_ids)
                rows = []
                for old_doc_id in old_doc_ids:
                    conn.execute("INSERT INTO supersession_edges (old_doc_id, new_doc_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (old_doc_id, new_doc_id))
                    rows.append(conn.execute(
                        "UPDATE documents SET is_current = FALSE, superseded_by = %s, updated_at = NOW() WHERE id = %s RETURNING *",
                        (new_doc_id, old_doc_id),
                    ).fetchone())
        return [document_from_row(row) for row in rows if row]

    def list_version_chain(self, document_id: str) -> list[DocumentRecord]:
        rows = self._execute_all(
            """
            WITH RECURSIVE related(id) AS (
                VALUES (%s::uuid)
                UNION
                SELECT CASE
                    WHEN edge.old_doc_id = related.id THEN edge.new_doc_id
                    ELSE edge.old_doc_id
                END
                FROM related
                JOIN supersession_edges edge
                    ON edge.old_doc_id = related.id OR edge.new_doc_id = related.id
            )
            SELECT * FROM documents WHERE id IN (SELECT id FROM related)
            ORDER BY COALESCE(effective_date, DATE '0001-01-01'), id
            """,
            (document_id,),
        )
        return [document_from_row(row) for row in rows]

    def list_superseded_document_ids(self, document_id: str) -> list[str]:
        rows = self._execute_all(
            """
            SELECT old_doc_id::text AS doc_id
            FROM supersession_edges
            WHERE new_doc_id = %s
            ORDER BY old_doc_id::text
            """,
            (document_id,),
        )
        return [str(row["doc_id"]) for row in rows]

    def append_audit_event(self, **kwargs: Any) -> None:
        self._execute_one(
            """
            INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
            VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id
            """,
            (
                kwargs["event_type"],
                kwargs["actor_id"],
                kwargs["target_type"],
                kwargs["target_id"],
                json.dumps(kwargs["payload"]),
            ),
        )

    def list_audit_events(self, *, limit: int = 100) -> list[AuditEventRecord]:
        rows = self._execute_all(
            """
            SELECT id::text, event_type, actor_id::text, target_type, target_id::text, payload, created_at
            FROM audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (max(1, min(limit, 5000)),),
        )
        return [audit_event_from_row(row) for row in rows]

    def replace_document_image_assets(
        self,
        *,
        doc_id: str,
        job_id: str,
        assets: list[dict[str, Any]],
    ) -> list[DocumentImageAssetRecord]:
        with self._connect() as conn:
            with conn.transaction():
                exists = conn.execute("SELECT 1 FROM documents WHERE id = %s AND deleted_at IS NULL", (doc_id,)).fetchone()
                if not exists:
                    raise ValueError("document does not exist")
                conn.execute("DELETE FROM document_image_assets WHERE doc_id = %s", (doc_id,))
                rows = []
                for asset in assets:
                    rows.append(
                        conn.execute(
                            """
                            INSERT INTO document_image_assets (
                                id, doc_id, job_id, source_kind, page, bbox, object_path, content_type,
                                width, height, content_hash, extracted_text, caption, confidence, quality_flags
                            )
                            VALUES (
                                COALESCE(%s::uuid, gen_random_uuid()), %s, %s, %s, %s, %s::jsonb,
                                %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                            )
                            RETURNING *
                            """,
                            (
                                asset.get("id"),
                                doc_id,
                                job_id,
                                asset.get("source_kind") or "image",
                                asset.get("page"),
                                json.dumps(asset.get("bbox")),
                                asset["object_path"],
                                asset.get("content_type") or "image/jpeg",
                                asset.get("width"),
                                asset.get("height"),
                                asset["content_hash"],
                                asset.get("extracted_text"),
                                asset.get("caption"),
                                asset.get("confidence"),
                                json.dumps(asset.get("quality_flags") or []),
                            ),
                        ).fetchone()
                    )
        return [image_asset_from_row(row) for row in rows if row]

    def list_document_image_assets(self, document_id: str) -> list[DocumentImageAssetRecord]:
        rows = self._execute_all(
            """
            SELECT *
            FROM document_image_assets
            WHERE doc_id = %s
            ORDER BY COALESCE(page, 0), created_at, id
            """,
            (document_id,),
        )
        return [image_asset_from_row(row) for row in rows]

    def get_document_image_asset(self, document_id: str, asset_id: str) -> DocumentImageAssetRecord | None:
        row = self._execute_optional(
            """
            SELECT *
            FROM document_image_assets
            WHERE doc_id = %s AND id = %s
            """,
            (document_id, asset_id),
        )
        return image_asset_from_row(row) if row else None


def validate_edges(conn: Any, new_doc_id: str, old_doc_ids: list[str]) -> None:
    if len(set(old_doc_ids)) != len(old_doc_ids):
        raise ValueError("supersedes contains duplicate document ids")
    for old_doc_id in old_doc_ids:
        _validate_edge(conn, new_doc_id, old_doc_id)


def document_from_row(row: dict[str, Any]) -> DocumentRecord:
    pending = row.get("pending_supersedes") or []
    shared = tuple(str(value) for value in _json_list(row.get("shared_group_paths")))
    return DocumentRecord(
        id=str(row["id"]),
        title=row.get("title"),
        source_id=row["source_id"],
        group_path=row["group_path"],
        clearance_level=normalize_clearance_level(row.get("clearance_level")),
        doc_type=row.get("doc_type"),
        language=row.get("language"),
        effective_date=row.get("effective_date"),
        expiry_date=row.get("expiry_date"),
        description=row.get("description"),
        summary=row.get("summary"),
        topics=tuple(str(value) for value in _json_list(row.get("topics"))),
        llm_topics=tuple(str(value) for value in _json_list(row.get("llm_topics"))),
        auto_doc_type=row.get("auto_doc_type"),
        extracted_dates=_json_object(row.get("extracted_dates")),
        metadata_flags=_json_object(row.get("metadata_flags")),
        is_current=bool(row["is_current"]),
        superseded_by=str(row["superseded_by"]) if row.get("superseded_by") else None,
        pending_supersedes=tuple(str(value) for value in pending),
        content_hash=row.get("content_hash"),
        uploaded_by=str(row["uploaded_by"]) if row.get("uploaded_by") else None,
        file_path=row.get("file_path"),
        ingest_status=row["ingest_status"],
        deleted_at=row.get("deleted_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        shared_group_paths=shared,
    )


def image_asset_from_row(row: dict[str, Any]) -> DocumentImageAssetRecord:
    bbox = row.get("bbox")
    flags = row.get("quality_flags")
    return DocumentImageAssetRecord(
        id=str(row["id"]),
        doc_id=str(row["doc_id"]),
        job_id=str(row["job_id"]) if row.get("job_id") else None,
        source_kind=str(row.get("source_kind") or "image"),
        page=row.get("page"),
        bbox=[float(item) for item in bbox] if isinstance(bbox, list) else None,
        object_path=str(row["object_path"]),
        content_type=str(row.get("content_type") or "image/jpeg"),
        width=int(row["width"]) if row.get("width") is not None else None,
        height=int(row["height"]) if row.get("height") is not None else None,
        content_hash=str(row["content_hash"]),
        extracted_text=str(row["extracted_text"]) if row.get("extracted_text") is not None else None,
        caption=str(row["caption"]) if row.get("caption") is not None else None,
        confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
        quality_flags=tuple(str(item) for item in flags) if isinstance(flags, list) else tuple(),
        created_at=row.get("created_at"),
    )


def _validate_edge(conn: Any, new_doc_id: str, old_doc_id: str) -> None:
    if old_doc_id == new_doc_id:
        raise ValueError("document cannot supersede itself")
    exists = conn.execute("SELECT 1 FROM documents WHERE id = %s AND deleted_at IS NULL", (old_doc_id,)).fetchone()
    if not exists:
        raise ValueError(f"superseded document does not exist: {old_doc_id}")
    cycle = conn.execute(
        """
        WITH RECURSIVE reach(id) AS (
            VALUES (%s::uuid)
            UNION SELECT new_doc_id FROM supersession_edges JOIN reach ON old_doc_id = reach.id
        )
        SELECT 1 FROM reach WHERE id = %s::uuid LIMIT 1
        """,
        (new_doc_id, old_doc_id),
    ).fetchone()
    if cycle:
        raise ValueError("supersession would create a cycle")


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            normalized.append(text)
    return normalized
