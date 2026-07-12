"""Run scheduled cleanup of expired generated artifacts."""

from __future__ import annotations

import argparse
import logging
import time

from rag.core.config import settings
from rag.repositories.postgres import PostgresConnectionMixin
from rag.services.generated_artifact_cleanup import (
    GeneratedArtifactCleanupError,
    GeneratedArtifactCleanupResult,
    cleanup_expired_generated_artifacts,
)


logger = logging.getLogger("rag.artifact_maintenance")
ADVISORY_LOCK_ID = 867530903
DEFAULT_CLEANUP_BATCH_SIZE = 500


class _LockConnection(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Delete expired generated artifacts.")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.loop and not args.once:
        args.once = True

    while True:
        try:
            result = _run_with_lock()
            if result is not None:
                logger.info(
                    "artifact cleanup scanned=%d deleted=%d missing=%d skipped=%d "
                    "jobs_scanned=%d jobs_deleted=%d jobs_skipped=%d "
                    "orphans_scanned=%d orphans_deleted=%d orphans_skipped=%d",
                    result.scanned_count,
                    result.deleted_count,
                    result.missing_object_count,
                    result.skipped_count,
                    result.scanned_job_count,
                    result.deleted_job_count,
                    result.skipped_job_count,
                    result.scanned_orphan_count,
                    result.deleted_orphan_count,
                    result.skipped_orphan_count,
                )
        except GeneratedArtifactCleanupError as exc:
            logger.error(
                "artifact cleanup failed failures=%d",
                len(exc.result.failures),
                exc_info=True,
            )
            if not args.loop:
                raise
        if not args.loop:
            return
        time.sleep(settings.artifact_maintenance_interval_seconds)


def _run_with_lock() -> GeneratedArtifactCleanupResult | None:
    if settings.document_repository != "postgres":
        return cleanup_expired_generated_artifacts(limit=DEFAULT_CLEANUP_BATCH_SIZE)
    lock = _LockConnection(settings.database_url)
    with lock._connect() as conn:
        acquired = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired",
            (ADVISORY_LOCK_ID,),
        ).fetchone()["acquired"]
        if not acquired:
            return None
        try:
            return cleanup_expired_generated_artifacts(limit=DEFAULT_CLEANUP_BATCH_SIZE)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))


if __name__ == "__main__":
    main()
