# Ingestion capability

This package owns the complete document-ingestion lifecycle. Runtime entrypoints
under `backend/apps/workers/document_pipeline` should only configure Celery and
call this package.

- `contracts.py` defines the producer/worker wire payload.
- `queue.py`, `recovery.py`, and `worker_control.py` manage dispatch and recovery.
- `execution.py` builds worker dependencies and executes one ingestion job.
- `pipeline/` defines the ordered ingestion workflow.
- `parsers/`, `chunking/`, `metadata/`, and `indexing/` implement pipeline work.
- `adapters/` contains concrete clients for storage, inference, and backend APIs.
- `ops/` contains ingestion-specific command-line operations.

Keep contracts and quality rules free of runtime I/O. Keep business behavior in
this package rather than in Celery task entrypoints or API routes. Add another
subdirectory only when a cohesive area has enough code to justify it.
