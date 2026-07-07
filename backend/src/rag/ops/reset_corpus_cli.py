"""Reset local pilot corpus metadata and Qdrant points."""

from __future__ import annotations

import argparse

from ..core.config import settings
from ..query.http import ServiceRequestError, request_json


def main() -> None:
    args = _parse_args()
    if not args.confirm_reset_local_corpus:
        raise SystemExit("Refusing to reset without --confirm-reset-local-corpus.")
    _delete_qdrant_collection()
    deleted = _truncate_corpus_rows()
    print(f"deleted_qdrant_collection={settings.qdrant_collection}")
    print(f"reset_database_tables={','.join(deleted)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-reset-local-corpus", action="store_true")
    return parser.parse_args()


def _delete_qdrant_collection() -> None:
    path = f"/collections/{settings.qdrant_collection}"
    try:
        request_json(
            settings.qdrant_url,
            path,
            service="qdrant",
            method="DELETE",
            timeout_seconds=settings.rag_http_timeout_seconds,
        )
    except ServiceRequestError as exc:
        if exc.status_code != 404:
            raise


def _truncate_corpus_rows() -> list[str]:
    with _connect() as conn:
        with conn.transaction():
            conn.execute("TRUNCATE TABLE documents CASCADE")
            conn.execute(
                """
                INSERT INTO audit_log (event_type, target_type, payload)
                VALUES ('rag.local_corpus_reset', 'corpus', jsonb_build_object('qdrant_collection', %s::text))
                """,
                (settings.qdrant_collection,),
            )
    return [
        "documents",
        "ingest_jobs",
        "claims",
        "conflicts",
        "supersession_edges",
        "human_review_queue",
        "image_review_candidates",
        "image_review_batches",
    ]


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required to reset the local corpus") from exc
    return psycopg.connect(settings.database_url)


if __name__ == "__main__":
    main()
