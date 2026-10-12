"""Fenced PostgreSQL persistence for checkpoint references."""

from __future__ import annotations

from datetime import datetime
from rag.shared.persistence import PostgresConnectionMixin

from ..models import CheckpointDescriptor, CheckpointLeaseLost


class PostgresCheckpointRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def commit(
        self, descriptor: CheckpointDescriptor, *, run_token: str
    ) -> CheckpointDescriptor:
        with self._connect() as conn:
            with conn.transaction():
                _lock_job(conn, descriptor, run_token)
                existing = conn.execute(
                    "SELECT * FROM ingest_checkpoints WHERE job_id = %s AND stage_key = %s FOR UPDATE",
                    (descriptor.job_id, descriptor.stage_key),
                ).fetchone()
                if existing is not None:
                    current = _descriptor(existing)
                    if current != descriptor:
                        raise ValueError("checkpoint already exists with different content")
                    return current
                row = conn.execute(
                    """
                    INSERT INTO ingest_checkpoints (
                        job_id, document_id, stage_key, object_key, schema_version,
                        body_sha256, compressed_size, decoded_size, upstream_sha256,
                        configuration_digest, range_start, range_end, model_identity,
                        vector_dimension
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        descriptor.job_id,
                        descriptor.document_id,
                        descriptor.stage_key,
                        descriptor.object_key,
                        descriptor.schema_version,
                        descriptor.body_sha256,
                        descriptor.compressed_size,
                        descriptor.decoded_size,
                        descriptor.upstream_sha256,
                        descriptor.configuration_digest,
                        descriptor.range_start,
                        descriptor.range_end,
                        descriptor.model_identity,
                        descriptor.vector_dimension,
                    ),
                ).fetchone()
        return _descriptor(row)

    def invalidate(self, descriptor: CheckpointDescriptor, *, run_token: str) -> bool:
        """Remove only the observed reference, while still owning the live job."""
        with self._connect() as conn:
            with conn.transaction():
                _lock_job(conn, descriptor, run_token)
                row = conn.execute(
                    "SELECT * FROM ingest_checkpoints WHERE job_id = %s AND stage_key = %s FOR UPDATE",
                    (descriptor.job_id, descriptor.stage_key),
                ).fetchone()
                if row is None:
                    return True
                if _descriptor(row) != descriptor:
                    return False
                conn.execute(
                    "DELETE FROM ingest_checkpoints WHERE job_id = %s AND stage_key = %s",
                    (descriptor.job_id, descriptor.stage_key),
                )
        return True

    def get(
        self, *, job_id: str, stage_key: str, run_token: str | None = None
    ) -> CheckpointDescriptor | None:
        if run_token is not None:
            _check_job_token(self, job_id, run_token)
        row = self._execute_optional(
            "SELECT * FROM ingest_checkpoints WHERE job_id = %s AND stage_key = %s",
            (job_id, stage_key),
        )
        return _descriptor(row) if row else None

    def list(self, *, job_id: str, stage_prefix: str) -> tuple[CheckpointDescriptor, ...]:
        rows = self._execute_all(
            "SELECT * FROM ingest_checkpoints WHERE job_id = %s AND stage_key LIKE %s ORDER BY stage_key",
            (job_id, f"{stage_prefix}%"),
        )
        return tuple(_descriptor(row) for row in rows)

    def expired(self, *, before: datetime, limit: int) -> tuple[CheckpointDescriptor, ...]:
        if limit <= 0:
            return ()
        rows = self._execute_all(
            """
            SELECT c.*
            FROM ingest_checkpoints c
            JOIN ingest_jobs j ON j.id = c.job_id
            WHERE j.status IN ('complete', 'failed', 'cancelled')
              AND COALESCE(j.completed_at, j.updated_at) < %s
            ORDER BY c.updated_at
            LIMIT %s
            """,
            (before, limit),
        )
        return tuple(_descriptor(row) for row in rows)

    def delete(self, *, job_id: str, stage_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "DELETE FROM ingest_checkpoints WHERE job_id = %s AND stage_key = %s RETURNING job_id",
                (job_id, stage_key),
            ).fetchone()
        return row is not None


def _lock_job(conn, descriptor: CheckpointDescriptor, run_token: str) -> None:
    job = conn.execute(
        """
        SELECT j.doc_id::text AS document_id, j.status, j.run_token, d.deleted_at
        FROM ingest_jobs j JOIN documents d ON d.id = j.doc_id
        WHERE j.id = %s FOR UPDATE OF j, d
        """,
        (descriptor.job_id,),
    ).fetchone()
    if job is None or job.get("deleted_at") is not None:
        raise CheckpointLeaseLost("ingestion job or live document is unavailable")
    if str(job["document_id"]) != descriptor.document_id:
        raise ValueError("checkpoint document does not match the job")
    if job["status"] != "processing" or str(job.get("run_token") or "") != run_token:
        raise CheckpointLeaseLost("ingestion job lease is no longer valid")


def _check_job_token(repository: PostgresCheckpointRepository, job_id: str, run_token: str) -> None:
    row = repository._execute_optional(
        """
        SELECT j.status, j.run_token, d.deleted_at
        FROM ingest_jobs j JOIN documents d ON d.id = j.doc_id
        WHERE j.id = %s
        """,
        (job_id,),
    )
    if row is None or row.get("deleted_at") is not None or row["status"] != "processing" or str(row.get("run_token") or "") != run_token:
        raise CheckpointLeaseLost("ingestion job lease is no longer valid")


def _descriptor(row: dict[str, object]) -> CheckpointDescriptor:
    return CheckpointDescriptor(
        job_id=str(row["job_id"]),
        document_id=str(row["document_id"]),
        stage_key=str(row["stage_key"]),
        object_key=str(row["object_key"]),
        schema_version=int(row["schema_version"]),
        body_sha256=str(row["body_sha256"]),
        compressed_size=int(row["compressed_size"]),
        decoded_size=int(row["decoded_size"]),
        upstream_sha256=str(row["upstream_sha256"]),
        configuration_digest=str(row["configuration_digest"]),
        range_start=int(row["range_start"]) if row.get("range_start") is not None else None,
        range_end=int(row["range_end"]) if row.get("range_end") is not None else None,
        model_identity=str(row["model_identity"]) if row.get("model_identity") is not None else None,
        vector_dimension=int(row["vector_dimension"]) if row.get("vector_dimension") is not None else None,
    )
