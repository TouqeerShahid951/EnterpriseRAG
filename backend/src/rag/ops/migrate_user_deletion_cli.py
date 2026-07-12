"""Idempotent migration enabling user deletion with immutable audit history."""

from __future__ import annotations

from rag.core.config import settings
from rag.shared.persistence import PostgresConnectionMixin


MIGRATION_SQL = """
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_actor_id_fkey;

COMMENT ON COLUMN audit_log.actor_id IS
    'Historical actor identifier retained after account deletion; intentionally not a foreign key because audit rows are immutable.';
"""


class _Migrator(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    migrator = _Migrator(settings.database_url)
    with migrator._connect() as conn:
        conn.execute(MIGRATION_SQL)
    print("User deletion schema migration complete.")


if __name__ == "__main__":
    main()
