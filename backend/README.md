# AgenticRAG backend

The backend is a Python modular monolith. It uses the standard `src` layout so
local tests and production run the same installable package rather than importing
code accidentally from the repository root.

## Layout

- `apps/` contains deployable composition roots: process startup, dependency
  wiring, task registration, healthchecks, and loop configuration. It may import
  `rag`, but reusable behavior does not belong here.
- `src/rag/` contains the installable application package, organized by product
  capability. It must not import `apps`.
- `tests/` contains capability-aligned unit, integration, and contract tests.
- `pyproject.toml` and `uv.lock` define the general backend environment used by
  the API and lightweight workers and background services. The document-pipeline
  image owns its heavier environment in
  `apps/workers/document_pipeline/pyproject.toml` and the adjacent `uv.lock`.

The `src` directory is not a Python package and must not contain an
`__init__.py`. Import application code through `rag`, for example
`rag.ingestion.contracts`.

## Dependency direction

Dependencies point toward feature rules and contracts:

```text
apps/composition ──> HTTP routes
        │
        └──────────> concrete adapters ──> feature contracts/domain

HTTP routes ──> application services ──> feature contracts/domain
```

Contracts do not import adapters. Application services do not import process
entrypoints, and reusable code under `src/rag` never imports `apps`.

## Feature boundaries

- Keep business behavior in `src/rag`, not in `apps` entrypoints.
- Keep feature-specific routes, schemas, application services, contracts,
  persistence adapters, and tests with their owning capability.
- Put concrete adapters under the feature that owns the contract, for example
  `rag.documents.adapters` or `rag.evaluations.adapters`. Do not create a global
  adapter directory that merely replaces the existing repository directory.
- Let routes depend on application services or public repository contracts, not
  concrete Postgres, in-memory, queue, storage, or scanner implementations.
- Access another capability through its public service or contract rather than
  importing private implementation details.
- Keep `rag.shared` small and limited to genuinely cross-capability code.
- Keep application services independent of FastAPI and Celery so their behavior
  can be tested without a transport or worker process.
- Add abstractions and subdirectories only when current complexity justifies
  them.

The former global `rag.repositories` package has been removed. Feature packages
own their repository contracts and adapters; only shared PostgreSQL connection
mechanics live in `rag.shared.persistence`. The global `rag.services` and
`rag.schemas` packages remain transitional and should move only with a tested
feature migration. Folder scheduling is now owned end to end by `rag.ingestion`:
its route and schemas sit beside transport-neutral scheduling and dispatch
services, while the API and folder-scheduler process only supply dependencies.
Generated-artifact lifecycle behavior is likewise owned by `rag.artifact_jobs`:
HTTP contracts, job actions, storage contracts, cleanup, delivery orchestration,
and concrete adapters live together, while API composition, Celery task
registration, and maintenance process modules remain thin entrypoints around
feature dependency providers. Artifact Celery registration is owned by
`apps.workers.artifact.tasks`; the durable retry and lease policy remains in
`rag.artifact_jobs.task_execution`. Its registered task name intentionally stays
`rag.artifact_jobs.tasks.generate_artifact_job` as an opaque compatibility
identifier for queued messages, even though that Python module no longer exists.
Evaluation follows the same boundary: `apps.workers.evaluation.tasks` owns
Celery registration, while cancellation and retry policy remain in
`rag.evaluations.task_execution`. The historic
`rag.evaluations.tasks.run_evaluation` task identifier remains compatible even
though its former feature module has been removed.
Document ingestion and GraphRAG registration is owned by
`apps.workers.document_pipeline.tasks`. Ingestion execution and retry decisions
remain in `rag.ingestion.execution`; GraphRAG indexing, rebuild deduplication,
and event policy remain in `rag.graphrag.task_execution`. Historic
`apps.ingestion.tasks.*` identifiers stay registered as compatibility aliases
when a deployment configures newer task names.
Public query transport is owned by `rag.query`:
its aggregate router composes separate session-history, source-discovery, and
query-execution routes, while query request and response contracts live in the
same feature. `apps/api` only includes that aggregate router. Query maps public
requests into the immutable `rag.artifact_jobs` submission contract before
delegating generated-artifact work, so artifact application services do not
depend on query transport DTOs. Citation, attribution, and conflict models used
by multiple capabilities are canonically owned by `rag.shared.contracts.evidence`;
`rag.query.schemas` explicitly re-exports them to preserve the public Python and
OpenAPI contracts while internal code imports the shared owner directly.
Authorized corpus access is exposed through the transport-neutral
`rag.retrieval.contracts` port. Artifact generation owns its planning, coverage,
retry, and manifest rules, while the query-runtime adapter encapsulates routing,
ABAC and lifecycle filters, Qdrant access, and reranking. Artifact application
code never receives raw query state, Qdrant hits, or caller-built storage
filters.

Artifact planning and composition depend on the narrow
`rag.artifact_jobs.generation.ArtifactJsonGenerator` contract. The concrete
query-runtime adapter translates provider failures and is the only artifact
adapter allowed to depend on query inference internals. Artifact request text
normalization is owned by `rag.artifact_jobs.request_text` and reused by query
intake. Deterministic fallbacks handle only known provider, timeout, and invalid
model-output failures; worker lifecycle interruptions continue to the task
boundary. Job cancellation is checked between generation calls, so an in-flight
provider request remains bounded by its configured HTTP timeout.

## Query citations and faithfulness

Query answers stream directly from one generation pass and use the existing
bracketed source labels. Adaptive faithfulness uses the local reranker for clear,
directly cited answers and sends uncertain or higher-risk answers to the AI judge.
Always sends every eligible answer to the judge; Never skips answer judging.

Source access and revision checks still run before response delivery. Evidence is
fit automatically within the route's evidence budget and the deployed model's
configured context window.

## Operational query analytics

The query owner stores historical execution metadata and bounded evidence lineage
under `rag.query.analytics`. Platform Admin APIs live at
`/api/v1/admin/query-analytics`; the browser page is `/operational-analytics`.
Default aggregates include production chat answers only (`origin=chat`,
`work_kind=answer`). Select another population explicitly, or use `all` for either
filter. P50/P95 stage timings sum retries within each execution first.

Analytics access does not grant conversation or document-content access. Candidate
capture and historical responses omit titles, evidence text and freeform errors;
the inspector displays identifiers, scores and timing metadata. Collection errors
emit safe warnings and queries continue, so stored rows cannot prove complete
capture during outages. Repository construction performs no DDL: API bootstrap
owns the idempotent analytics schema.

Compose configures `query-analytics-maintenance` using the API image. It runs every
`QUERY_ANALYTICS_MAINTENANCE_INTERVAL_SECONDS` (default 300 seconds), bounded by
`QUERY_ANALYTICS_MAINTENANCE_BATCH_SIZE` (default 500 per cleanup category; summary
deletion shares its budget with reconciliation when that is explicitly invoked).
`QUERY_ANALYTICS_LINEAGE_RETENTION_DAYS` defaults to seven days after completion;
expiry removes evidence/quality detail and preserves pipeline timings.
`QUERY_ANALYTICS_RETENTION_DAYS` defaults to 30 days from request start for terminal
summaries and 30 days from occurrence for boundary events. Active executions are
not deleted.

New executions heartbeat during blocking work and streaming, including tracker,
evaluation and artifact-submission paths. The interval is the smaller of 30
seconds or one third of `QUERY_ANALYTICS_RECONCILIATION_GRACE_SECONDS`; its default
3600 seconds is the maximum heartbeat silence, not a query-duration limit.
Maintenance considers only rows with a recorded heartbeat and an expired renewed
deadline. It records `interrupted` with `reason_code=analytics_heartbeat_expired`;
the UI calls this **Heartbeat overdue** and explains that interruption is inferred.
With the default five-minute cleanup interval, detection normally occurs within
60–65 minutes of the last successful heartbeat, plus any cleanup backlog.

Heartbeat storage failures log a safe warning and do not cancel queries. A returning
heartbeat restores an inferred interruption to in-flight; an actual final result
can replace the inference. Genuine terminal outcomes remain immutable. Inferred
interruptions retain their summary for 30 days after reconciliation, allowing
late recovery even for a request that started outside the retention window.
Older rows without heartbeat tracking are never reconciled from age alone and
appear as **Status unknown**. No liveness data is fabricated for historical rows.

After rebuilding the normal images and starting the service, inspect its health
and successful-cycle logs. The heartbeat is updated only after success. For a
manual bounded cycle through the existing CLI:

```bash
docker compose run --rm --no-deps query-analytics-maintenance python -m rag.ops.query_analytics_maintenance --once
docker compose exec query-analytics-maintenance python -m apps.background.query_analytics_cleanup --healthcheck
docker compose logs --tail=20 query-analytics-maintenance
```

The CLI exits nonzero on failure; the scheduled process retries and becomes
unhealthy when its last success is stale. No backfill is performed. The deployment
status and validation record are in
[`docs/implementation-plans/operational-analytics/README.md`](../docs/implementation-plans/operational-analytics/README.md).

## Runtime processes

The deployment has four kinds of long-running process:

- **API:** `api` serves HTTP through the FastAPI composition root in `apps/api`.
- **Queue workers:** `artifact-worker`, `ingestion-worker`, `graphrag-worker`,
  and `evaluation-worker` consume Celery queues. Ingestion and GraphRAG are
  separate services with different queues, but intentionally share the heavy
  document-pipeline Celery app, image, and worker configuration.
- **Background services:** `artifact-maintenance`, `folder-scheduler`,
  `ingest-maintenance`, and `query-analytics-maintenance` are separate containers
  and operating-system processes, not Celery workers. They clean expired
  artifacts, enqueue due folder ingestions, recover or fail stale ingestion jobs,
  and expire query analytics, respectively.
- **Deployment control:** `deployment-controller` is an internal, request-driven
  control-plane service. It serializes authenticated vLLM apply requests and
  recreates only allowlisted Compose services through the Docker socket. It is
  packaged separately from the API and does not process user requests directly.

Workers react to individual queued messages. Background services wake on a
schedule, inspect system state, perform one maintenance cycle and sleep. They use
owner-specific advisory or row locks for concurrent work. Process startup and loop wiring belong in `apps`; the
cleanup, scheduling, and recovery behavior belongs to its owning feature under
`src/rag`.

Reusable feature code under `src/rag` does not register Celery tasks. Worker
registration and transport-specific retry translation belong under
`apps/workers`; feature packages own the durable execution policy they invoke.

The general backend image and the document-pipeline image each install from one
manifest and its adjacent lockfile. Docker builds use locked production syncs and
must fail when a manifest and lock disagree. The document worker's CPU PyTorch
index and exact Torch baseline belong to its `pyproject.toml`; Dockerfiles do not
override package versions, and no shared constraints file competes with either
lock.

## Configuration ownership

Configuration is layered by lifecycle rather than stored in one physical file:

```text
saved workspace configuration -> environment bootstrap -> Python defaults
```

- `rag.query` owns live model routing and query behavior. A validated workspace
  record in PostgreSQL is authoritative; environment values are its bootstrap
  fallback.
- `rag.ingestion` owns worker boot and parser settings. Workers obtain the live
  RAG runtime record from the internal API when a task executes.
- Folder scheduling receives a small immutable `FolderIngestionConfig` from its
  API or background composition root; scheduling and dispatch code do not read
  the global `Settings` object at import or execution time.
- `rag.deployment` owns desired vLLM launch limits and applies them through the
  deployment controller.
- `core.config.Settings` is the typed compatibility facade for process
  environment values. It does not decide workspace-over-environment precedence.
- Docker Compose owns container topology and explicitly distributes only the
  environment values needed by backend processes. Dockerfiles do not own
  mutable RAG behavior.

Changing `.env` does not replace an existing workspace RAG record. A Platform
Admin must use **Restore deployment defaults** to remove the saved record before
the environment fallback becomes effective.

The ingestion package has a more detailed ownership map in
[`src/rag/ingestion/README.md`](src/rag/ingestion/README.md).
Deployment control has its ownership and privilege boundary documented in
[`src/rag/deployment/README.md`](src/rag/deployment/README.md).

## Development checks

From this directory:

```bash
uv lock --check
uv lock --check --project apps/workers/document_pipeline
uv sync --locked --extra dev
.venv/bin/ruff check apps src tests
.venv/bin/python -m pytest tests
```

From the repository root, validate deployment wiring with:

```bash
docker compose config --quiet
docker compose build ingestion-worker
```

### Document attention and recovery

The Document Overview counts current, non-deleted, authorized documents.
Attention is exactly `failed`, `human_review`, or `unknown`; cancelled documents
are counted separately, alongside indexed and processing states. Attention
entries include the latest job's safe error and timestamp for that visible
document. A mismatched latest job state is shown explicitly, not interpreted as
resolution. These are persisted ingestion states, not a live vector-index audit.

The browser's `lifecycle=current&ingest=attention` filter matches this definition.
Reingestion acceptance is reported as queued, not successful indexing. Recent
recovery attempts remain available on document pages after a document leaves a
failed filter; the five latest attempts link to the full ingestion history.
Job status changes refresh document snapshots. Overview scope is all documents
visible to the account, explicitly labeled; document-list space filters remain
available for narrower inspection.
