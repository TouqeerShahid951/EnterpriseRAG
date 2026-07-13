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
- `pyproject.toml` and `uv.lock` define the installable backend environment.

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
feature dependency providers.

## Runtime processes

The deployment has four kinds of long-running process:

- **API:** `api` serves HTTP through the FastAPI composition root in `apps/api`.
- **Queue workers:** `artifact-worker`, `ingestion-worker`, `graphrag-worker`,
  and `evaluation-worker` consume Celery queues. Ingestion and GraphRAG are
  separate services with different queues, but intentionally share the heavy
  document-pipeline Celery app, image, and worker configuration.
- **Background services:** `artifact-maintenance`, `folder-scheduler`, and
  `ingest-maintenance` are separate containers and operating-system processes,
  not Celery workers. They periodically clean expired artifacts, enqueue due
  folder ingestions, and recover or fail stale ingestion jobs, respectively.
- **Deployment control:** `deployment-controller` is an internal, request-driven
  control-plane service. It serializes authenticated vLLM apply requests and
  recreates only allowlisted Compose services through the Docker socket. It is
  packaged separately from the API and does not process user requests directly.

Workers react to individual queued messages. Background services wake on a
schedule, inspect system state, perform one maintenance cycle under a PostgreSQL
advisory lock, and sleep. Process startup and loop wiring belong in `apps`; the
cleanup, scheduling, and recovery behavior belongs to its owning feature under
`src/rag`.

Some worker composition and background command modules still live under
`src/rag` while the architecture is migrated. That is known transitional
placement, not a precedent for feature code to depend on deployment wiring.

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
uv sync --extra dev
.venv/bin/ruff check apps src tests
.venv/bin/python -m pytest tests
```

From the repository root, validate deployment wiring with:

```bash
docker compose config --quiet
docker compose build ingestion-worker
```
