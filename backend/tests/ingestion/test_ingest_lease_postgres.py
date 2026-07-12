from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from rag.repositories.document_postgres import PostgresDocumentRepository


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL lease integration coverage",
)
def test_postgres_attempt_fencing_and_terminal_race() -> None:
    assert TEST_DATABASE_URL is not None
    repo = PostgresDocumentRepository(TEST_DATABASE_URL)
    with repo._connect() as conn:
        conn.execute(
            "ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS run_token TEXT NULL"
        )
    group_path = f"/lease-{uuid4().hex[:12]}"
    with repo._connect() as conn:
        conn.execute(
            "INSERT INTO groups (path, name) VALUES (%s, %s)",
            (group_path, "Lease integration test"),
        )
    source_id = f"lease-test:{uuid4()}"
    document = repo.create_document(
        title="Lease integration test",
        source_id=source_id,
        group_path=group_path,
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=None,
        file_path="memory://lease-test.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="queued",
    )
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="queued",
        progress_pct=0,
        origin="upload",
    )

    try:
        def claim(worker: int):
            worker_repo = PostgresDocumentRepository(TEST_DATABASE_URL)
            return worker_repo.start_ingest_attempt(
                job.id,
                max_attempts=3,
                stale_after_seconds=120,
                run_token=f"worker-{worker}",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(claim, range(8)))

        winners = [claim for claim in claims if claim.claimed]
        assert len(winners) == 1
        assert winners[0].job is not None
        winning_token = winners[0].job.run_token
        assert winning_token is not None

        repeated = repo.start_ingest_attempt(
            job.id,
            max_attempts=3,
            stale_after_seconds=120,
            run_token=winning_token,
        )
        assert repeated.claimed is True
        assert repeated.job is not None and repeated.job.attempt_count == 1

        with repo._connect() as conn:
            conn.execute(
                """
                UPDATE ingest_jobs
                SET last_heartbeat_at = NOW() - INTERVAL '5 minutes'
                WHERE id = %s
                """,
                (job.id,),
            )

        takeover = repo.start_ingest_attempt(
            job.id,
            max_attempts=3,
            stale_after_seconds=120,
            run_token="worker-current",
        )
        assert takeover.claimed is True
        assert takeover.job is not None and takeover.job.run_token == "worker-current"

        assert repo.heartbeat_ingest_job(job.id, run_token=winning_token).changed is False
        assert repo.heartbeat_ingest_job(job.id, run_token=None).changed is False
        assert repo.update_ingest_job(
            job.id,
            status="complete",
            progress_pct=100,
            expected_statuses=frozenset({"processing"}),
            run_token=winning_token,
        ).changed is False
        assert repo.update_ingest_job(
            job.id,
            status="complete",
            progress_pct=100,
            expected_statuses=frozenset({"processing"}),
            run_token=None,
        ).changed is False
        assert repo.record_ingest_parser_provenance(
            job.id,
            provenance={"parser": "stale"},
            run_token=winning_token,
        ) is None
        assert repo.record_ingest_parser_provenance(
            job.id,
            provenance={"parser": "current"},
            run_token="worker-current",
        ) is not None
        assert repo.update_ingest_job(
            job.id,
            status="processing",
            progress_pct=80,
            stage_progress={"label": "newer"},
            run_token="worker-current",
        ).changed is True
        assert repo.update_ingest_job(
            job.id,
            status="processing",
            progress_pct=40,
            stage_progress={"label": "older"},
            run_token="worker-current",
        ).changed is True
        monotonic = repo.get_ingest_job(job.id)
        assert monotonic is not None
        assert monotonic.progress_pct == 80
        assert monotonic.stage_progress == {"label": "newer"}

        def complete():
            worker_repo = PostgresDocumentRepository(TEST_DATABASE_URL)
            return worker_repo.update_ingest_job(
                job.id,
                status="complete",
                progress_pct=100,
                expected_statuses=frozenset({"processing"}),
                run_token="worker-current",
            )

        def cancel():
            worker_repo = PostgresDocumentRepository(TEST_DATABASE_URL)
            return worker_repo.cancel_ingest_job(
                job.id,
                allowed_statuses=frozenset(
                    {"scheduled", "queued", "processing", "human_review"}
                ),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            complete_future = pool.submit(complete)
            cancel_future = pool.submit(cancel)
            complete_result = complete_future.result()
            cancel_result = cancel_future.result()

        assert int(complete_result.changed) + int(cancel_result.changed) == 1
        final = repo.get_ingest_job(job.id)
        assert final is not None
        assert final.status in {"complete", "cancelled"}
        assert final.run_token is None
    finally:
        with repo._connect() as conn:
            with conn.transaction():
                conn.execute(
                    "DELETE FROM audit_log WHERE target_id = %s",
                    (job.id,),
                )
                conn.execute("DELETE FROM documents WHERE id = %s", (document.id,))
                conn.execute("DELETE FROM groups WHERE path = %s", (group_path,))
