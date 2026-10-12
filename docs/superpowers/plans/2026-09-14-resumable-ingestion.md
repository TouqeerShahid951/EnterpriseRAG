# Resumable Ingestion Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement task by task. The user requested Luna with extra-high reasoning (`gpt-5.6-luna`, `xhigh`) for subsequent implementation. Application changes and deployment have not started.

**Goal:** Reuse durably completed ingestion work after worker failure, including an explicitly linked manual retry, without publishing an incomplete replacement index.

**Architecture:** Save stage outputs and embedding batches in existing object storage, with a small PostgreSQL registry protected by the job's current run token. Restore validated outputs into the existing pipeline and replay its existing Qdrant staging, verification, publication and activation workflow. Resume occurs at completed stage/batch boundaries, not inside interrupted model calls.

**Tech stack:** Python, JSON/gzip/hashlib, existing MinIO/PostgreSQL clients, Celery, FastEmbed/Ollama/OpenAI-compatible adapters and Qdrant. No new dependency or workflow engine.

**Spec:** The user's request to continue failed ingestion; repository `AGENTS.md`, `PRODUCT.md`, `backend/README.md` and `backend/src/rag/ingestion/README.md` govern ownership and compatibility.

## Review findings

1. **Avoid changing publication to achieve resume.** `indexing/qdrant.py:stage_generation` currently deletes the unpublished generation before writing it. Incrementally saving batches there would require changing staging, verification, retry and retirement behavior. Store vector batches in object storage instead; a failed index-write stage can replay without embedding again.
2. **A job-scoped object alone is unsafe.** `adapters/backend.py:ensure_lease` checks a local flag, not a database lock. A stale worker could overwrite a mutable checkpoint after another attempt starts. Upload immutable objects and register references only under a database transaction checking the current run token.
3. **The existing digest is insufficient.** `pipeline/indexing_stages.py:_configuration_digest` contains three chunk sizes and the quality preset. It omits model/provider identity, reviews and actual embedding inputs. Matching vector dimensions does not establish compatible embeddings.
4. **Manual retries are new jobs.** `documents/lifecycle/reingestion_service.py` persists `retry_of_job_id` in PostgreSQL, not the worker payload. Explicit predecessor adoption must be implemented; same-job checkpoints alone would not help after retry exhaustion.
5. **Resume does not fix the worker kill.** Logs show local FastEmbed loading followed by SIGKILL. Memory pressure is suspected, but the exact kill cause is not established. A failing unsaved batch can fail again. Preserve retry limits and separately verify resource use on Zero Trust before calling that document recovered.

## Scope and compatibility

- Implement in the common pipeline for ordinary PDF, DOCX, PPTX, image, JSON and spreadsheet vector ingestion. Zero Trust is the first rollout sample, not a PDF-specific code branch.
- Save after successful extraction including review gates and asset persistence; after metadata enrichment; after chunk/claim preparation; and after each dense or sparse embedding batch. Metadata can mutate parsed spreadsheet items, so save the enriched items too.
- A retry with 16 saved vectors reports `Resuming embeddings: 16 of 210 chunks saved`, then processes the next missing range. A crash before durable commit repeats that range. No exactly-once model-execution guarantee.
- A crash during parsing repeats that stage. Per-page parser checkpoints remain deferred; existing OCR/image review resumption remains authoritative.
- Qdrant writes may repeat using saved vectors. The existing current-generation and authorization filters must continue excluding incomplete replacements.
- Automatic recovery retains the current three-failure limit. Explicit retries linked to failed/cancelled jobs may adopt compatible work. Unlinked Reingest starts fresh. Terminal jobs never resume merely because a stale message arrives.
- Legacy jobs have no saved artifacts. Their next run must compute and save work before later retries can resume; prior lost memory cannot be recovered.
- Keep public HTTP shapes, queue names and registered task names. Add only internal checkpoint transport and a versioned schema migration. Do not change citation generation, introduce cross-document caches, adaptive batch sizing or new workers.
- Preserve unrelated worktree changes; no broad staging or cleanup. Application implementation is a subsequent step.

## Durable data

Use explicit versioned JSON, not pickle or a dump of `IngestState`. Never restore credentials, leases, job status, source paths or access controls from artifacts.

| Artifact | Contents | Next work |
| --- | --- | --- |
| `parsed` | Parsed items, provenance, warnings, image asset descriptors and review digest | Metadata |
| `metadata` | Enriched parsed items, metadata, provenance, warnings and assets | Chunking |
| `prepared` | Full chunks including citation targets, metadata, claims, warnings, provenance, assets and exact embedding texts | Dense embeddings |
| `dense/start/end` | Ordered vectors and input hashes for a half-open chunk range | Next missing dense range |
| `sparse/start/end` | Ordered sparse indices/values and input hashes | Next missing sparse range |

Each registry entry binds job/document id, schema/stage version, upstream artifact checksum, configuration fingerprint, body checksum, sizes and object key. Vector entries also bind model identity, range and dimension. Registered, validated artifacts are authoritative; a UI counter is not a checkpoint.

Fingerprint resolved values passed from dependency composition, respecting saved-workspace precedence:

- **Extraction:** source SHA-256, format, parser implementation version, effective parser/OCR/vision settings and model identities, slide/table options, and approved review contents. Use existing review APIs, including `get_review_batch_parsed_items` and `get_image_review_resume`, where applicable.
- **Preparation:** upstream checksum, metadata model/provider and prompt version, taxonomy/GLiNER options, relevant document metadata, chunker and embedding-text construction versions, and chunk settings.
- **Vectors:** prepared checksum, exact ordered input hashes, dense/sparse model identity, provider, preprocessing version and model revision/digest where exposed. Mutable remote model names without an exposed revision remain a documented limitation; use fresh unlinked Reingest after replacing such a model.
- Timeouts/concurrency do not invalidate semantic outputs. Freeze logical ranges at preparation using the existing batch-size setting (default 16). A provider may execute smaller sub-batches within a saved range without discarding completed ranges.

Recompute an incompatible stage and its dependents. An embedding-model change can keep extraction/preparation while invalidating that model's vectors. Validate complete range coverage, vector counts, finite values, dimensions, sparse indices and all citation-target fields. Missing/corrupt batches are explicitly invalidated and recomputed; storage outages and authorization failures are retryable operational failures, not cache misses.

Bound gzip/JSON decoding: initially 64 MiB compressed and 256 MiB decoded per artifact, owned as ingestion constants. Exceeding the limit raises `checkpoint_too_large`; never truncate text or silently advertise unsaved work as resumable. Do not add UI settings for these limits.

## Task 1: Fenced storage and serialization

**Files:** Create `backend/src/rag/ingestion/checkpoints/{models.py,service.py,repository.py,schemas.py,routes.py,dependencies.py,schema.py}` and `checkpoints/adapters/{postgres.py,storage.py}`, with package markers. Modify `backend/src/rag/bootstrap/schema.py`, `backend/apps/api/main.py` and `backend/src/rag/ingestion/adapters/backend.py` for wiring. Keep I/O in adapters and policy in the owning service.

**Interfaces:** `CheckpointService.load(job_id, run_token, stage_key)` resolves a committed reference; `commit(job_id, run_token, artifact_descriptor)` registers an uploaded immutable object. Typed descriptors contain the identity, checksum, range and size fields above. Storage exposes read/write/delete for generated checkpoint keys only.

- [ ] Add `ingest_checkpoints`, keyed by `(job_id, stage_key)` with a foreign key to jobs and the reference metadata above. Use the established idempotent bootstrap pattern. Bodies belong in object storage.
- [ ] Add service-token transport under `/internal/ingest/jobs/{job_id}/checkpoints`. Resolve document scope from the job; validate generated keys under `ingest-checkpoints/{document_id}/{job_id}/`. Do not accept arbitrary paths, buckets or cross-document artifact requests.
- [ ] Upload immutable objects using content checksum and an attempt-specific suffix. Under the job row lock, require `processing`, current run token, a live document and matching upstream reference before registering a checkpoint. Repeated identical commits are idempotent. Reject stale commits with existing lease-loss semantics and inconsistent commits with a specific checkpoint conflict.
- [ ] Verify schema, checksum, sizes, complete required fields and fingerprint on load. Reuse parser serializers, but validate at this boundary instead of letting defaults convert missing fields into valid empty output. Validate new chunk/vector serialization explicitly, preserving source spans and citation targets.
- [ ] Add `backend/tests/ingestion/test_ingest_checkpoints.py` and `test_ingest_checkpoint_routes.py`: round-trip citation/table data; malformed vectors; decompression limits; outages versus missing objects; wrong document; stale run token; duplicate commit; and uncertain upload/commit responses.

Commit ordering:

```text
validate/serialize -> upload immutable object -> commit reference under current
database lease -> report durably saved progress
```

Killing a worker between upload and registry commit leaves an ignored orphan. A late worker may create an orphan, but cannot overwrite the current checkpoint or advance its registry entry.

## Task 2: Restore stages and embed only missing ranges

**Files:** Create `backend/src/rag/ingestion/pipeline/resume.py`. Modify `pipeline/{graph.py,state.py,steps.py,indexing_stages.py}` and `execution.py`. Add `backend/tests/ingestion/test_ingest_resume.py`; extend existing pipeline, image-review and OCR-review tests.

- [ ] Compose the checkpoint client and explicit fingerprint inputs in `execution.py`. Claim the job and check the live source/review context before restoring. Restore payload/configuration from current owners, never from an artifact.
- [ ] At each existing stage boundary, restore compatible output or run and commit the stage. Do not checkpoint extraction as complete while review is pending. Preserve image asset descriptors and verify their stored objects before reuse. Re-register provenance/assets via existing APIs when adopting another job.
- [ ] Persist exact prepared chunks, claims and embedding texts before embedding. Preserve all citation fields, parent relationships and warnings. Glossaries retain their no-embedding path and abbreviation entries.
- [ ] Put the durable batch loop in the pipeline. For dense ranges, restore or call `deps.inference.embed_many` on the missing range; validate, save and commit. Do the same separately for sparse ranges through `SparseEmbedder.embed_many`. Preserve provider-local retries. A sparse failure must not discard saved dense work.
- [ ] Provider progress callbacks only report completed computations, not durability. Report saved progress after checkpoint commit, using global chunk totals in existing `stage_progress` fields.
- [ ] Reassemble vectors in chunk order for the existing point builder and stage/verify/publish/activate sequence. Do not store ready-made Qdrant payloads containing stale ACL/lifecycle data. Refresh that context through its owner before staging; checkpoint reuse must not revive deleted/inaccessible documents.
- [ ] Keep Qdrant replay behavior and complete verification. After an uncertain activation response, terminal-job handling must prevent replaying destructive staging against an active generation. Unused parser models must not load on a resume from prepared output. Final vector/point assembly retains existing memory bounds; do not claim peak memory is solved.

Algorithm:

```text
for logical range in prepared artifact:
    check lease and cancellation
    restore matching committed vector batch if available
    otherwise compute, validate, upload and fenced-commit this range
    append in original order and report saved total
run existing publication stages using the current job's generation
```

- [ ] Regression: use 40 synthetic chunks with range size 16. Interrupt while computing dense range 16–31. Restart with a fresh worker context sharing only persistent stores. Assert no parse/metadata calls, no model call for 0–15, and model inputs 16–31 then 32–39. If 0–15 was uploaded but not committed, assert it is recomputed.
- [ ] Also test sparse failure; corrupt/missing middle batch; changed source/model/chunker/metadata settings; enriched spreadsheet items; pending/edited reviews; glossary bypass; and interruptions before/after staging, verification, publication and activation. Compare resumed and uninterrupted ordered outputs, provenance and vector counts.

## Task 3: Linked manual retry and progress semantics

**Files:** Extend the checkpoint service/repository/routes and `pipeline/resume.py`. Keep `documents/lifecycle/reingestion_service.py` and queue payload behavior compatible. Cover `backend/tests/documents/lifecycle/test_reingestion_service.py`, `backend/tests/ingestion/test_ingest_resume.py` and `frontend/src/features/upload/state/uploadJobProgress.test.ts`.

- [ ] For a new job with no local artifacts, resolve its immediate `retry_of_job_id` from PostgreSQL. Require a failed/cancelled predecessor for the same document; allow only compatible, unexpired, committed artifacts. Unlinked reingestion does not adopt prior work.
- [ ] Copy validated artifacts to the new job's own prefix and commit its own references. Do not reuse the predecessor's index generation, hold dependencies on its cleanup, or traverse an unbounded retry chain. Require matching current approvals; otherwise rerun affected review/extraction stages.
- [ ] If cleanup removes an artifact during copying, recompute the missing stage explicitly; storage outages remain retryable. A committed copy is independent of predecessor retention.
- [ ] Show `Restored parsed document`, `Resuming embeddings: 16 of 210 chunks saved`, and `Rewriting index from saved vectors` through existing progress fields. Clear stale stage details when recovery queues another attempt. Make the smallest change in the existing progress owner; no new dashboard or public status values.
- [ ] Test linked retry after exhaustion, cross-document rejection, cancellation, fresh unlinked reingest, expired checkpoints, changed access metadata, and retries of a job that previously adopted artifacts.

## Task 4: Cleanup, diagnostics and release verification

**Files:** Extend checkpoint service/adapters and `backend/src/rag/ingestion/maintenance.py`; compose cleanup in `backend/apps/background/ingestion_maintenance.py`. Update ingestion README and `docs/manuals/operator-manual.md`. Add architecture/transport coverage under `backend/tests/architecture/` and cleanup tests to the checkpoint tests.

- [ ] Delete checkpoints after successful activation, with idempotent maintenance retry if deletion fails. A cleanup failure cannot turn an activated job into a failed job. Retain terminal failed/cancelled artifacts for seven days; exclude active/queued/review jobs from age cleanup. Deleted-document artifacts are cleanup candidates.
- [ ] Sweep unregistered objects older than 24 hours under the checkpoint prefix, excluding live-job prefixes and rechecking registry references. Run bounded cleanup of 100 objects per existing maintenance cycle. Delete objects before registry references so partial cleanup remains diagnosable. Never delete source uploads or image assets as checkpoint garbage.
- [ ] Log job/attempt, stage/range, saved/restored counts, duration, provider/model identity and safe reason codes. For embedding diagnosis capture input lengths and worker memory metadata; never log text, vectors, credentials or full endpoint URLs.
- [ ] Validate local FastEmbed, Ollama and OpenAI-compatible adapters with deterministic tests. Provider names must not alter checkpoint policy. Run focused tests before broader owner/architecture checks.

```bash
uv run --directory backend --locked --extra dev python -m pytest tests/ingestion/test_ingest_checkpoints.py tests/ingestion/test_ingest_checkpoint_routes.py tests/ingestion/test_ingest_resume.py
uv run --directory backend --locked --extra dev python -m pytest tests/ingestion tests/documents/lifecycle tests/architecture
uv run --directory backend --locked --extra dev ruff check apps src tests
npm --prefix frontend test -- src/features/upload/state/uploadJobProgress.test.ts
docker compose config --quiet
```

- [ ] Build affected API/document-worker images using existing lockfiles; verify imports/health. Run a controlled termination integration test on an isolated test job after a batch commit. Assert restoration in a replacement process, no duplicate points, and no visibility of partial replacements. Do not kill an active user job as an uncontrolled experiment.
- [ ] Deploy schema/API and maintenance support before the ingestion worker; drain active work before replacement. Older workers can ignore the additive checkpoint schema during rollback. Maintenance can remove unused artifacts.
- [ ] Use Zero Trust as the first real sample. Verify saved/restored counts, peak memory, stage timing, provenance, final activation and retrieval. Repeated death on the same unsaved batch fails acceptance: investigate the resource/input failure before declaring that document recovered. Do not increase retries indefinitely or truncate its content.

## Completion criteria

1. A fresh worker restores committed stages/batches and repeats only missing or incompatible computations.
2. Linked manual retries after exhaustion can adopt compatible work; fresh Reingest computes new outputs.
3. Stale workers, duplicates, cancellations, edited reviews and changed model/source inputs cannot corrupt checkpoints or cause invalid reuse.
4. Storage and cleanup failures produce safe actionable diagnostics; retention never removes a live job's artifacts.
5. Provenance, review gates, document authorization and index activation pass regression checks, including crash/uncertain-response boundaries.

**Complexity:** Moderate, with meaningful storage and recovery tests. The first draft understated lease handling and manual retry semantics. This revision avoids incremental Qdrant publication; persisted outputs, fenced commits, compatibility checks and cleanup are the remaining correctness requirements.
