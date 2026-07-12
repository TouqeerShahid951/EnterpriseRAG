"""Dispatch due scheduled folder ingestion jobs."""

from __future__ import annotations

import argparse
import time

from rag.core.config import settings
from rag.connectors.repositories import get_connector_profile_repository
from rag.query.qdrant import QdrantClient
from rag.repositories.documents import get_document_repository
from rag.repositories.folder_schedules import get_folder_schedule_repository
from rag.repositories.ingest_jobs import ingest_job_repository_for
from rag.repositories.postgres import PostgresConnectionMixin
from rag.services.folder_ingestion import dispatch_due_schedules
from rag.services.folder_sources import get_local_folder_source, get_minio_prefix_source
from rag.ingestion.queue import get_ingest_queue
from rag.services.upload_storage import get_upload_storage

ADVISORY_LOCK_ID = 867530901


class _LockConnection(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch due folder ingestion schedules.")
    parser.add_argument("--loop", action="store_true", help="Run forever, checking every configured interval.")
    parser.add_argument("--once", action="store_true", help="Dispatch due schedules once and exit.")
    args = parser.parse_args()

    if not args.loop and not args.once:
        args.once = True

    while True:
        dispatched = _dispatch_with_lock()
        if dispatched:
            print(f"dispatched_folder_schedules={','.join(dispatched)}")
        if not args.loop:
            return
        time.sleep(max(5, settings.folder_scheduler_interval_seconds))


def _dispatch_with_lock() -> list[str]:
    if settings.document_repository == "postgres":
        lock = _LockConnection(settings.database_url)
        with lock._connect() as conn:
            acquired = conn.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (ADVISORY_LOCK_ID,)).fetchone()["acquired"]
            if not acquired:
                return []
            try:
                return _dispatch()
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
    return _dispatch()


def _dispatch() -> list[str]:
    document_repo = get_document_repository()
    return dispatch_due_schedules(
        schedule_repo=get_folder_schedule_repository(),
        document_repo=document_repo,
        job_repo=ingest_job_repository_for(document_repo),
        queue=get_ingest_queue(),
        minio_source=get_minio_prefix_source(),
        local_folder_source=get_local_folder_source(),
        connector_profile_repo=get_connector_profile_repository(),
        storage=get_upload_storage(),
        qdrant=QdrantClient(
            base_url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            timeout_seconds=settings.rag_http_timeout_seconds,
        ),
    )


if __name__ == "__main__":
    main()
