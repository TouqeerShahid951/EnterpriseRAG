"""Run ingestion recovery and worker-capacity maintenance."""

from __future__ import annotations

import argparse
import time

from apps.background.watchdog import heartbeat
from rag.core.config import settings
from rag.ingestion.maintenance import (
    reconcile_ingestion_jobs,
    retire_index_generations,
)
from rag.shared.persistence import PostgresConnectionMixin


ADVISORY_LOCK_ID = 867530902


class _LockConnection(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Maintain ingestion worker capacity and recover stale jobs."
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.loop and not args.once:
        args.once = True

    heartbeat()
    while True:
        recovered = _run_with_lock()
        heartbeat()
        if recovered:
            print(f"recovered_ingest_jobs={','.join(recovered)}", flush=True)
        if not args.loop:
            return
        time.sleep(settings.ingest_maintenance_interval_seconds)


def _run_with_lock() -> list[str]:
    if settings.document_repository != "postgres":
        return _run_maintenance()
    lock = _LockConnection(settings.database_url)
    with lock._connect() as conn:
        acquired = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired",
            (ADVISORY_LOCK_ID,),
        ).fetchone()["acquired"]
        if not acquired:
            return []
        try:
            return _run_maintenance()
        finally:
            conn.execute(
                "SELECT pg_advisory_unlock(%s)",
                (ADVISORY_LOCK_ID,),
            )


def _run_maintenance() -> list[str]:
    recovered = reconcile_ingestion_jobs()
    retire_index_generations()
    return recovered


if __name__ == "__main__":
    main()
