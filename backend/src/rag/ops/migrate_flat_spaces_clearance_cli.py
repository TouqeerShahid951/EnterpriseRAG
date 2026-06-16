"""Migrate Knowledge Spaces to flat paths and add NATO clearance columns."""

from __future__ import annotations

import argparse
from typing import Any

from rag.core.config import settings
from rag.repositories.postgres import PostgresConnectionMixin


CLEARANCE_CHECK = "('NATO_UNCLASSIFIED','NATO_RESTRICTED','NATO_CONFIDENTIAL','NATO_SECRET','COSMIC_TOP_SECRET')"


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    args = _parse_args()
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        nested = _nested_groups(conn)
        blockers = _blockers(conn, nested)
        _print_report(nested, blockers)
        if args.dry_run:
            print("dry_run=true")
            return
        if not args.confirm_flatten_clearance:
            raise SystemExit("Refusing to mutate without --confirm-flatten-clearance.")
        if blockers:
            raise SystemExit("Nested Knowledge Spaces still have documents, users, or schedules.")
        with conn.transaction():
            _add_clearance_columns(conn)
            _delete_empty_nested_groups(conn, nested)
            _enforce_flat_groups(conn)
        print("flat Knowledge Space and clearance migration complete.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--confirm-flatten-clearance", action="store_true")
    args = parser.parse_args()
    if args.confirm_flatten_clearance:
        args.dry_run = False
    return args


def _nested_groups(conn: Any) -> list[str]:
    parent_clause = "OR COALESCE(parent_path, '') <> ''" if _has_column(conn, "groups", "parent_path") else ""
    rows = conn.execute(
        f"""
        SELECT path
        FROM groups
        WHERE path LIKE '/%/%'
           {parent_clause}
        ORDER BY path
        """
    ).fetchall()
    return [str(row["path"]) for row in rows]


def _blockers(conn: Any, nested: list[str]) -> list[dict[str, object]]:
    if not nested:
        return []
    rows = conn.execute(
        """
        SELECT path,
               (SELECT COUNT(*) FROM documents WHERE group_path = path) AS documents,
               (SELECT COUNT(*) FROM user_groups WHERE group_path = path) AS users,
               (SELECT COUNT(*) FROM folder_ingest_schedules WHERE group_path = path) AS schedules
        FROM unnest(%s::text[]) AS nested(path)
        ORDER BY path
        """,
        (nested,),
    ).fetchall()
    return [
        dict(row)
        for row in rows
        if int(row["documents"]) or int(row["users"]) or int(row["schedules"])
    ]


def _print_report(nested: list[str], blockers: list[dict[str, object]]) -> None:
    print(f"nested_groups={len(nested)}")
    for path in nested[:20]:
        print(f"nested_group={path}")
    if len(nested) > 20:
        print(f"nested_group_preview_truncated={len(nested) - 20}")
    print(f"blocking_nested_groups={len(blockers)}")
    for blocker in blockers:
        print(
            "blocker "
            f"path={blocker['path']} documents={blocker['documents']} "
            f"users={blocker['users']} schedules={blocker['schedules']}"
        )


def _add_clearance_columns(conn: Any) -> None:
    conn.execute(f"""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED';
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED';
        ALTER TABLE folder_ingest_schedules ADD COLUMN IF NOT EXISTS clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED';
        ALTER TABLE IF EXISTS artifact_generation_jobs ADD COLUMN IF NOT EXISTS clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED';
        ALTER TABLE IF EXISTS rag_evaluation_runs ADD COLUMN IF NOT EXISTS clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED';

        UPDATE users SET clearance_level = 'COSMIC_TOP_SECRET' WHERE account_type = 'platform_admin';

        DO $$
        BEGIN
            PERFORM 1;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_clearance_level_known') THEN
                ALTER TABLE users ADD CONSTRAINT users_clearance_level_known CHECK (clearance_level IN {CLEARANCE_CHECK});
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'documents_clearance_level_known') THEN
                ALTER TABLE documents ADD CONSTRAINT documents_clearance_level_known CHECK (clearance_level IN {CLEARANCE_CHECK});
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'folder_ingest_schedules_clearance_level_known') THEN
                ALTER TABLE folder_ingest_schedules ADD CONSTRAINT folder_ingest_schedules_clearance_level_known CHECK (clearance_level IN {CLEARANCE_CHECK});
            END IF;
        END $$;
    """)


def _delete_empty_nested_groups(conn: Any, nested: list[str]) -> None:
    if not nested:
        return
    conn.execute("DELETE FROM groups WHERE path = ANY(%s::text[])", (nested,))


def _enforce_flat_groups(conn: Any) -> None:
    conn.execute(
        """
        ALTER TABLE groups DROP COLUMN IF EXISTS parent_path;
        ALTER TABLE groups DROP CONSTRAINT IF EXISTS groups_path_format;
        ALTER TABLE groups ADD CONSTRAINT groups_path_format
            CHECK (path ~ '^/[a-z0-9][a-z0-9-]*$');
        CREATE INDEX IF NOT EXISTS documents_clearance_level_idx ON documents (clearance_level);
        CREATE INDEX IF NOT EXISTS folder_ingest_schedules_clearance_level_idx
            ON folder_ingest_schedules (clearance_level);
        """
    )


def _has_column(conn: Any, table: str, column: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        (table, column),
    ).fetchone()
    return row is not None


if __name__ == "__main__":
    main()
