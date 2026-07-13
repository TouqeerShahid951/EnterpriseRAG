"""PostgreSQL folder schedule repository."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ....auth.abac import normalize_group_path
from ....shared.persistence import PostgresConnectionMixin
from ....shared.contracts.clearance import normalize_clearance_level
from ..models import FolderRunItemRecord, FolderRunRecord, FolderScheduleRecord


class PostgresFolderScheduleRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create_schedule(self, **kwargs: Any) -> FolderScheduleRecord:
        row = self._execute_one(
            """
            INSERT INTO folder_ingest_schedules (
                name, source_type, schedule_type, status, group_path, clearance_level, doc_type,
                effective_date, expiry_date, description, timezone, scheduled_at,
                recurrence, source_config, created_by, next_run_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (
                kwargs["name"].strip(),
                kwargs["source_type"],
                kwargs["schedule_type"],
                kwargs["status"],
                normalize_group_path(kwargs["group_path"]),
                normalize_clearance_level(kwargs.get("clearance_level")),
                kwargs.get("doc_type"),
                kwargs["effective_date"],
                kwargs.get("expiry_date"),
                kwargs.get("description"),
                kwargs["timezone"],
                kwargs.get("scheduled_at"),
                json.dumps(kwargs.get("recurrence") or {}),
                json.dumps(kwargs.get("source_config") or {}),
                kwargs.get("created_by"),
                kwargs.get("next_run_at"),
            ),
        )
        return schedule_from_row(row)

    def list_schedules(self) -> list[FolderScheduleRecord]:
        rows = self._execute_all(
            "SELECT * FROM folder_ingest_schedules ORDER BY created_at DESC"
        )
        return [schedule_from_row(row) for row in rows]

    def list_due_schedules(
        self, now: datetime, *, limit: int = 20
    ) -> list[FolderScheduleRecord]:
        rows = self._execute_all(
            """
            SELECT * FROM folder_ingest_schedules
            WHERE status IN ('scheduled', 'active')
              AND next_run_at IS NOT NULL
              AND next_run_at <= %s
            ORDER BY next_run_at ASC, created_at ASC
            LIMIT %s
            """,
            (now, max(1, min(limit, 100))),
        )
        return [schedule_from_row(row) for row in rows]

    def get_schedule(self, schedule_id: str) -> FolderScheduleRecord | None:
        row = self._execute_optional(
            "SELECT * FROM folder_ingest_schedules WHERE id = %s", (schedule_id,)
        )
        return schedule_from_row(row) if row else None

    def delete_schedule(self, schedule_id: str) -> FolderScheduleRecord | None:
        row = self._execute_optional(
            "DELETE FROM folder_ingest_schedules WHERE id = %s RETURNING *",
            (schedule_id,),
        )
        return schedule_from_row(row) if row else None

    def update_schedule_status(
        self, schedule_id: str, *, status: str
    ) -> FolderScheduleRecord | None:
        row = self._execute_optional(
            "UPDATE folder_ingest_schedules SET status = %s, updated_at = NOW() WHERE id = %s RETURNING *",
            (status, schedule_id),
        )
        return schedule_from_row(row) if row else None

    def update_schedule_next_run(
        self, schedule_id: str, **kwargs: Any
    ) -> FolderScheduleRecord | None:
        row = self._execute_optional(
            """
            UPDATE folder_ingest_schedules
            SET status = COALESCE(%s, status), last_run_at = COALESCE(%s, last_run_at),
                next_run_at = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                kwargs.get("status"),
                kwargs.get("last_run_at"),
                kwargs.get("next_run_at"),
                schedule_id,
            ),
        )
        return schedule_from_row(row) if row else None

    def reschedule(
        self, schedule_id: str, **kwargs: Any
    ) -> FolderScheduleRecord | None:
        row = self._execute_optional(
            """
            UPDATE folder_ingest_schedules
            SET schedule_type = %s, scheduled_at = %s, recurrence = %s::jsonb,
                timezone = %s, next_run_at = %s, status = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                kwargs["schedule_type"],
                kwargs.get("scheduled_at"),
                json.dumps(kwargs.get("recurrence") or {}),
                kwargs["timezone"],
                kwargs.get("next_run_at"),
                "active" if kwargs["schedule_type"] == "recurring" else "scheduled",
                schedule_id,
            ),
        )
        return schedule_from_row(row) if row else None

    def create_run(
        self,
        *,
        schedule_id: str,
        status: str,
        due_at: datetime,
        started_at: datetime | None = None,
    ) -> FolderRunRecord:
        row = self._execute_one(
            """
            INSERT INTO folder_ingest_runs (schedule_id, status, due_at, started_at)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (schedule_id, status, due_at, started_at),
        )
        return run_from_row(row)

    def update_run(self, run_id: str, **kwargs: Any) -> FolderRunRecord | None:
        row = self._execute_optional(
            """
            UPDATE folder_ingest_runs
            SET status = %s,
                started_at = COALESCE(%s, started_at),
                completed_at = COALESCE(%s, completed_at),
                error_code = %s,
                error_message_safe = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                kwargs["status"],
                kwargs.get("started_at"),
                kwargs.get("completed_at"),
                kwargs.get("error_code"),
                kwargs.get("error_message_safe"),
                run_id,
            ),
        )
        return run_from_row(row) if row else None

    def list_runs(self, schedule_id: str) -> list[FolderRunRecord]:
        rows = self._execute_all(
            "SELECT * FROM folder_ingest_runs WHERE schedule_id = %s ORDER BY created_at DESC",
            (schedule_id,),
        )
        return [run_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> FolderRunRecord | None:
        row = self._execute_optional(
            "SELECT * FROM folder_ingest_runs WHERE id = %s", (run_id,)
        )
        return run_from_row(row) if row else None

    def create_run_item(self, **kwargs: Any) -> FolderRunItemRecord:
        row = self._execute_one(
            """
            INSERT INTO folder_ingest_run_items (
                run_id, schedule_id, source_path, filename, object_path, content_hash,
                size_bytes, content_type, status, skip_code, skip_message, document_id, job_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                kwargs["run_id"],
                kwargs["schedule_id"],
                kwargs["source_path"],
                kwargs["filename"],
                kwargs.get("object_path"),
                kwargs.get("content_hash"),
                kwargs.get("size_bytes"),
                kwargs.get("content_type"),
                kwargs.get("status", "scheduled"),
                kwargs.get("skip_code"),
                kwargs.get("skip_message"),
                kwargs.get("document_id"),
                kwargs.get("job_id"),
            ),
        )
        return item_from_row(row)

    def update_run_item_status(
        self, item_id: str, **kwargs: Any
    ) -> FolderRunItemRecord | None:
        row = self._execute_optional(
            """
            UPDATE folder_ingest_run_items
            SET status = %s, document_id = COALESCE(%s, document_id), job_id = COALESCE(%s, job_id),
                skip_code = %s, skip_message = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                kwargs["status"],
                kwargs.get("document_id"),
                kwargs.get("job_id"),
                kwargs.get("skip_code"),
                kwargs.get("skip_message"),
                item_id,
            ),
        )
        return item_from_row(row) if row else None

    def list_run_items(self, run_id: str) -> list[FolderRunItemRecord]:
        rows = self._execute_all(
            "SELECT * FROM folder_ingest_run_items WHERE run_id = %s ORDER BY created_at ASC",
            (run_id,),
        )
        return [item_from_row(row) for row in rows]

    def list_pending_items_for_schedule(
        self, schedule_id: str
    ) -> list[FolderRunItemRecord]:
        rows = self._execute_all(
            """
            SELECT * FROM folder_ingest_run_items
            WHERE schedule_id = %s AND status = 'scheduled'
            ORDER BY created_at ASC
            """,
            (schedule_id,),
        )
        return [item_from_row(row) for row in rows]

    def latest_document_for_source(
        self, schedule_id: str, source_path: str
    ) -> tuple[str, str | None] | None:
        row = self._execute_optional(
            """
            SELECT item.document_id::text, item.content_hash
            FROM folder_ingest_run_items item
            JOIN documents document ON document.id = item.document_id
            WHERE item.schedule_id = %s
              AND item.source_path = %s
              AND item.document_id IS NOT NULL
              AND document.deleted_at IS NULL
              AND document.is_current = TRUE
            ORDER BY item.created_at DESC
            LIMIT 1
            """,
            (schedule_id, source_path),
        )
        return (str(row["document_id"]), row.get("content_hash")) if row else None

    def has_source_content(
        self, schedule_id: str, source_path: str, content_hash: str
    ) -> bool:
        row = self._execute_optional(
            """
            SELECT 1 FROM folder_ingest_run_items item
            WHERE item.schedule_id = %s AND item.source_path = %s
              AND item.content_hash = %s AND item.document_id IS NOT NULL
            LIMIT 1
            """,
            (schedule_id, source_path, content_hash),
        )
        return row is not None

    def known_source_paths(self, schedule_id: str) -> set[str]:
        rows = self._execute_all(
            "SELECT DISTINCT source_path FROM folder_ingest_run_items WHERE schedule_id = %s AND document_id IS NOT NULL",
            (schedule_id,),
        )
        return {str(row["source_path"]) for row in rows}


def schedule_from_row(row: dict[str, Any]) -> FolderScheduleRecord:
    return FolderScheduleRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        source_type=str(row["source_type"]),
        schedule_type=str(row["schedule_type"]),
        status=str(row["status"]),
        group_path=str(row["group_path"]),
        clearance_level=normalize_clearance_level(row.get("clearance_level")),
        doc_type=str(row["doc_type"]) if row.get("doc_type") else None,
        effective_date=row["effective_date"],
        expiry_date=row.get("expiry_date"),
        description=row.get("description"),
        timezone=str(row["timezone"]),
        scheduled_at=row.get("scheduled_at"),
        recurrence=_json_object(row.get("recurrence")),
        source_config=_json_object(row.get("source_config")),
        created_by=str(row["created_by"]) if row.get("created_by") else None,
        last_run_at=row.get("last_run_at"),
        next_run_at=row.get("next_run_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def run_from_row(row: dict[str, Any]) -> FolderRunRecord:
    return FolderRunRecord(
        id=str(row["id"]),
        schedule_id=str(row["schedule_id"]),
        status=str(row["status"]),
        due_at=row["due_at"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        error_code=row.get("error_code"),
        error_message_safe=row.get("error_message_safe"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def item_from_row(row: dict[str, Any]) -> FolderRunItemRecord:
    return FolderRunItemRecord(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        schedule_id=str(row["schedule_id"]),
        source_path=str(row["source_path"]),
        filename=str(row["filename"]),
        object_path=row.get("object_path"),
        content_hash=row.get("content_hash"),
        size_bytes=int(row["size_bytes"])
        if row.get("size_bytes") is not None
        else None,
        content_type=row.get("content_type"),
        status=str(row["status"]),
        skip_code=row.get("skip_code"),
        skip_message=row.get("skip_message"),
        document_id=str(row["document_id"]) if row.get("document_id") else None,
        job_id=str(row["job_id"]) if row.get("job_id") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}
