"""PostgreSQL persistence for document index generations."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from rag.documents.ingestion import apply_staged_ingestion_data
from rag.shared.persistence import PostgresConnectionMixin

from ..models import IndexGeneration


class PostgresIndexPublicationRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def stage(
        self,
        *,
        generation_id: str,
        job_id: str,
        run_token: str,
        input_hash: str,
        configuration_digest: str,
        expected_point_count: int,
        expected_item_hash: str,
        vector_dimension: int,
        staged_metadata: dict[str, Any],
    ) -> IndexGeneration:
        with self._connect() as conn:
            with conn.transaction():
                job = _locked_job(conn, job_id, run_token)
                current = conn.execute(
                    "SELECT * FROM document_index_generations WHERE job_id = %s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if current is not None:
                    _require_matching_generation(
                        current, generation_id=generation_id, document_id=str(job["doc_id"])
                    )
                    if current["state"] == "active":
                        return _generation_from_row(current)
                    row = conn.execute(
                        """
                        UPDATE document_index_generations
                        SET state = 'building',
                            input_hash = %s,
                            configuration_digest = %s,
                            expected_point_count = %s,
                            expected_item_hash = %s,
                            vector_dimension = %s,
                            staged_metadata = %s::jsonb,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (
                            input_hash,
                            configuration_digest,
                            expected_point_count,
                            expected_item_hash,
                            vector_dimension,
                            json.dumps(staged_metadata),
                            generation_id,
                        ),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """
                        INSERT INTO document_index_generations (
                            id, document_id, job_id, input_hash, configuration_digest,
                            expected_point_count, expected_item_hash, vector_dimension,
                            staged_metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        RETURNING *
                        """,
                        (
                            generation_id,
                            job["doc_id"],
                            job_id,
                            input_hash,
                            configuration_digest,
                            expected_point_count,
                            expected_item_hash,
                            vector_dimension,
                            json.dumps(staged_metadata),
                        ),
                    ).fetchone()
        return _generation_from_row(_require_row(row, "index generation stage"))

    def mark_verified(
        self, *, generation_id: str, job_id: str, run_token: str
    ) -> IndexGeneration:
        with self._connect() as conn:
            with conn.transaction():
                job = _locked_job(conn, job_id, run_token)
                row = _locked_generation(conn, generation_id)
                _require_matching_generation(
                    row, generation_id=generation_id, document_id=str(job["doc_id"]), job_id=job_id
                )
                if row["state"] == "verified":
                    return _generation_from_row(row)
                if row["state"] != "building":
                    raise ValueError("index generation cannot be verified from its current state")
                row = conn.execute(
                    """
                    UPDATE document_index_generations
                    SET state = 'verified', updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (generation_id,),
                ).fetchone()
        return _generation_from_row(_require_row(row, "index generation verification"))

    def activate(
        self, *, generation_id: str, job_id: str, run_token: str
    ) -> IndexGeneration:
        with self._connect() as conn:
            with conn.transaction():
                job = _locked_job(conn, job_id, run_token)
                row = _locked_generation(conn, generation_id)
                document_id = str(job["doc_id"])
                _require_matching_generation(
                    row, generation_id=generation_id, document_id=document_id, job_id=job_id
                )
                document = conn.execute(
                    "SELECT id, active_index_generation_id FROM documents WHERE id = %s AND deleted_at IS NULL FOR UPDATE",
                    (document_id,),
                ).fetchone()
                if document is None:
                    raise ValueError("document does not exist")
                if row["state"] == "active" and str(document.get("active_index_generation_id") or "") == generation_id:
                    return _generation_from_row(row)
                if row["state"] != "verified":
                    raise ValueError("index generation must be verified before activation")

                staged = _staged_payload(row)
                metadata = _object(staged.get("metadata"))
                supersedes = _string_list(staged.get("supersedes"))
                apply_staged_ingestion_data(
                    conn,
                    document_id=document_id,
                    metadata=metadata,
                    claims=_list_of_objects(staged.get("claims")),
                    supersedes=supersedes,
                )

                conn.execute(
                    """
                    UPDATE document_index_generations
                    SET state = 'retiring', updated_at = NOW()
                    WHERE document_id = %s AND state = 'active' AND id <> %s
                    """,
                    (document_id, generation_id),
                )
                row = conn.execute(
                    """
                    UPDATE document_index_generations
                    SET state = 'active', activated_at = COALESCE(activated_at, NOW()), updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (generation_id,),
                ).fetchone()
                conn.execute(
                    """
                    UPDATE documents
                    SET active_index_generation_id = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (generation_id, document_id),
                )
                completed = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = 'complete',
                        progress_pct = 100,
                        warnings = COALESCE(%s::jsonb, warnings),
                        run_token = NULL,
                        updated_at = NOW(),
                        completed_at = NOW()
                    WHERE id = %s AND status = 'processing' AND run_token = %s
                    RETURNING id
                    """,
                    (
                        json.dumps(_string_list(staged.get("warnings"))),
                        job_id,
                        run_token,
                    ),
                ).fetchone()
                if completed is None:
                    raise ValueError("ingestion job lease is no longer valid")
                conn.execute(
                    """
                    UPDATE documents
                    SET ingest_status = 'complete', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (document_id,),
                )
                _append_activation_audit_events(
                    conn,
                    document_id=document_id,
                    job_id=job_id,
                    metadata=metadata,
                    supersedes=supersedes,
                )
        return _generation_from_row(_require_row(row, "index generation activation"))

    def cancel_building(self, *, job_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE document_index_generations
                SET state = 'retiring', updated_at = NOW()
                WHERE job_id = %s AND state IN ('building', 'verified')
                RETURNING id::text AS id
                """,
                (job_id,),
            ).fetchone()
        return str(row["id"]) if row else None

    def active_generation_ids(
        self,
        document_ids: list[str],
        current_only: bool,
    ) -> dict[str, str | None]:
        ids = _uuid_list(document_ids)
        if not ids:
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id::text AS document_id, active_index_generation_id::text AS generation_id
                FROM documents
                WHERE id = ANY(%s::uuid[])
                  AND deleted_at IS NULL
                  AND (%s::boolean = FALSE OR is_current = TRUE)
                """,
                (ids, current_only),
            ).fetchall()
        return {
            str(row["document_id"]): (
                str(row["generation_id"]) if row.get("generation_id") else None
            )
            for row in rows
        }

    def list_retiring(self, *, limit: int) -> tuple[IndexGeneration, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM document_index_generations
                WHERE state = 'retiring'
                ORDER BY updated_at, id
                LIMIT %s
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return tuple(_generation_from_row(row) for row in rows)

    def mark_retired(self, generation_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE document_index_generations
                SET state = 'retired', retired_at = COALESCE(retired_at, NOW()), updated_at = NOW()
                WHERE id = %s AND state = 'retiring'
                RETURNING id
                """,
                (generation_id,),
            ).fetchone()
        return row is not None


def _locked_job(conn: Any, job_id: str, run_token: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, doc_id, status, run_token FROM ingest_jobs WHERE id = %s FOR UPDATE",
        (job_id,),
    ).fetchone()
    if row is None:
        raise ValueError("ingestion job does not exist")
    if row["status"] != "processing" or row.get("run_token") != run_token:
        raise ValueError("ingestion job lease is no longer valid")
    return row


def _locked_generation(conn: Any, generation_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM document_index_generations WHERE id = %s FOR UPDATE",
        (generation_id,),
    ).fetchone()
    return _require_row(row, "index generation")


def _require_matching_generation(
    row: dict[str, Any],
    *,
    generation_id: str,
    document_id: str,
    job_id: str | None = None,
) -> None:
    if str(row["id"]) != generation_id or str(row["document_id"]) != document_id:
        raise ValueError("index generation does not match the ingestion job")
    if job_id is not None and str(row["job_id"]) != job_id:
        raise ValueError("index generation does not match the ingestion job")


def _append_activation_audit_events(
    conn: Any,
    *,
    document_id: str,
    job_id: str,
    metadata: dict[str, Any],
    supersedes: list[str],
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
        VALUES (%s, NULL, %s, %s, %s::jsonb)
        """,
        (
            "internal.document_metadata.saved",
            "document",
            document_id,
            json.dumps(
                {
                    "topics_count": len(_string_list(metadata.get("topics"))),
                    "llm_topics_count": len(_string_list(metadata.get("llm_topics"))),
                    "doc_type": _optional_text(
                        metadata.get("doc_type") or metadata.get("auto_doc_type")
                    ),
                    "metadata_version": metadata.get("metadata_version"),
                    "entities_count": len(_list_of_objects(metadata.get("named_entities"))),
                    "cross_references_count": len(
                        _list_of_objects(metadata.get("cross_references"))
                    ),
                }
            ),
        ),
    )
    if supersedes:
        conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
            VALUES (%s, NULL, %s, %s, %s::jsonb)
            """,
            (
                "internal.supersession.committed",
                "document",
                document_id,
                json.dumps({"superseded_doc_ids": supersedes}),
            ),
        )
    conn.execute(
        """
        INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
        VALUES (%s, NULL, %s, %s, %s::jsonb)
        """,
        (
            "internal.ingest.status",
            "ingest_job",
            job_id,
            json.dumps(
                {
                    "doc_id": document_id,
                    "status": "complete",
                    "progress_pct": 100,
                    "error_code": None,
                }
            ),
        ),
    )


def _staged_payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("staged_metadata")
    return value if isinstance(value, dict) else {}


def _generation_from_row(row: dict[str, Any]) -> IndexGeneration:
    return IndexGeneration(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        job_id=str(row["job_id"]),
        state=str(row["state"]),
        expected_point_count=int(row["expected_point_count"]),
        expected_item_hash=str(row["expected_item_hash"]),
        vector_dimension=int(row["vector_dimension"]),
    )


def _require_row(row: dict[str, Any] | None, operation: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"{operation} did not return a row")
    return row


def _uuid_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        try:
            normalized.append(str(UUID(str(value))))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(normalized))


def _object(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_objects(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip())) if isinstance(value, list) else []


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
