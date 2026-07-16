# Repository instructions for coding agents

This root guide applies to the whole repository. It defines the target structure
for new work; existing transitional modules are migration debt, not patterns to
copy. A future nested `AGENTS.md` may refine local conventions but must preserve
the dependency boundaries below.

## Before changing code

Read `PRODUCT.md`, `README.md`, `backend/README.md`, and the owning feature's
README when one exists. Treat the current source tree and
`backend/tests/architecture/` as more authoritative for code placement than
older path examples in design documents.

Inspect `git status` first. Preserve unrelated user changes and do not reset,
overwrite, stage, or commit work outside the requested slice.

Follow these rules:

- Give every behavior one product-capability owner.
- Every function, class, and module must have one responsibility describable in
  one sentence. Treat size as a review signal: split when responsibilities,
  side effects, test boundaries, or navigation concerns differ, not merely when
  a line-count threshold is crossed.
- Prefer a small complete vertical slice over a new global abstraction.
- Reuse an established feature pattern before adding a base class, registry,
  factory, generic service, or empty architectural layer.
- Split code by responsibility and test boundary, not merely by line count.
- Validate at HTTP, task, CLI, and deserialization boundaries. Fail explicitly;
  never swallow operational errors.
- Make retried jobs and operational commands idempotent where practical.
- Preserve public HTTP behavior, persisted payloads, queue names, and registered
  Celery task-name strings unless the change explicitly includes a migration.

## Repository map

| Path | Responsibility |
| --- | --- |
| `backend/apps/` | Deployable process composition only. |
| `backend/src/rag/` | Reusable backend features and application code. |
| `backend/tests/` | Capability tests and architecture contracts. |
| `frontend/src/app/` | Frontend application composition. |
| `frontend/src/features/` | Browser features grouped by capability. |
| `frontend/src/components/`, `lib/`, `types/` | Genuinely cross-feature frontend code. |
| `docs/` | Architecture, user, operator, and manual material. |
| `deploy/` | Tracked container startup and recovery assets. |
| `scripts/` | Repository-level checks and documentation builders. |
| `docker-compose.yml` | Deployment topology and environment distribution. |

Runtime contents under `folder-sources/` (except its tracked `.gitkeep`),
`model-cache/`, `tmp/`, `backups/`, `.env`, virtual environments, dependency
installs, caches, and build outputs are local data, not source. Root
`.env.example` documents Compose/backend deployment; `frontend/.env.example`
documents standalone frontend development.

Do not create a generic application `infra/` package. External I/O belongs in
the owning backend feature's `adapters/`; container assets belong in `deploy/`
or `docker-compose.yml`.

Markdown under `docs/manuals/` is the manual source of truth. Do not hand-edit
`docs/manuals/generated/`; regenerate it with `scripts/build_user_manuals.py`.

## Backend structure

The backend is a modular monolith with a standard `src` layout. Import through
`rag.*`; `backend/src/` is not a package and must not gain `__init__.py`.

```text
apps/composition ──> feature routes and dependency wiring
routes ────────────> application services ──> contracts/domain
concrete adapters ──────────────────────────> contracts/domain
```

Enforce the dependency direction:

- `backend/src/rag/` never imports `apps`.
- Contracts and domain rules never import adapters.
- Routes parse/authenticate input, invoke a use case, and map its result. They do
  not import concrete Postgres, memory, queue, storage, scanner, or external
  adapters.
- Application services own workflows and policy. Keep them independent of
  FastAPI and Celery; pass narrow typed configuration instead of reading global
  `Settings` inside pure logic.
- `dependencies.py` or a process composition root wires contracts to adapters.
- Cross-feature calls use the owner's public contract or service, not a private
  adapter or internal implementation module.

### Feature package target

Use only the entries the capability needs:

```text
backend/src/rag/CAPABILITY/
├── routes.py or routes/          # HTTP transport
├── schemas.py                    # Feature-owned wire schemas
├── models.py                     # Domain/application data
├── service.py or USE_CASE.py     # Application behavior
├── contracts.py / ports.py / repository.py
├── dependencies.py              # Composition providers
├── adapters/                     # Postgres, memory, queue, storage, external I/O
├── task_execution.py             # Durable worker policy, when needed
└── ops/                          # Feature-specific CLI operations, when needed

backend/tests/CAPABILITY/         # Tests mirroring ownership
```

Follow the owning feature's vocabulary; responsibilities matter more than
identical filenames. Extend an existing capability before creating a new one.
Keep a shared concept with its natural owner and expose a narrow public contract.
Use `rag.shared` only when there is no clearer owner, and keep shared contracts
dependency-light. `rag.core` is limited to application-wide configuration and
behavior.

Do not place new feature behavior in transitional `rag.api.routes`,
`rag.internal`, `rag.schemas`, or `rag.services`. New `/internal` routes may use
`rag.internal` as thin service-token HTTP transport, but their behavior,
schemas, contracts, and persistence remain with the owning capability. Do not
create global adapter/repository/service dumping grounds, generic base
repositories, or ambiguous registries.

### Implementing a backend slice

1. Choose the owner and state observable behavior and compatibility constraints.
2. Add domain rules, use cases, and narrow contracts with success, failure, and
   retry/idempotency tests.
3. Add concrete I/O under the feature's `adapters/` and wire it through a
   provider. Keep persistence/schema definitions with the feature and register
   idempotent bootstrap or repair through `rag.bootstrap.schema`, with
   compatibility coverage.
4. Add feature-owned schemas and thin routes. Preserve authorization, CSRF,
   status codes, and response shapes.
5. Compose a new aggregate router in `backend/apps/api/main.py` only if it is not
   already included.
6. Add a worker or background process only when the workload needs an independent
   queue, schedule, deployment lifecycle, or dependency environment.
7. Mirror tests under `backend/tests/CAPABILITY/`; add or update an architecture
   test for a new owner or boundary.

### Process and interface boundaries

- `apps/api/` is the FastAPI composition root. Compose services `api` and
  `query-api` use the same Python app/image; they are deployment replicas.
- `apps/workers/*/` owns Celery configuration, decorated task registration, and
  transport exception translation. Features own durable execution, retry,
  deduplication, cancellation, and event policy.
- `apps/workers/document_pipeline/` is the shared heavy runtime for the separate
  ingestion and GraphRAG queues.
- `apps/background/` contains independent periodic processes, not Celery tasks;
  their rules remain in their owning features.
- `apps/deployment_controller/` is privileged internal wiring. Docker execution
  stays in `rag.deployment.adapters.docker_compose` and remains allowlisted.

Celery task names are durable wire identifiers. Preserve historical names even
when they no longer match an importable module. Create durable job state before
enqueueing work so delivery failures are diagnosable and recoverable.

Public browser APIs live under `/api/v1`. Worker-facing `/internal` APIs require
the service token and must not become browser shortcuts. Public ingestion,
query, and artifact OpenAPI shapes are contract-tested under
`backend/tests/architecture/`.

## Frontend structure

```text
frontend/src/
├── app/                         # Providers and application composition
├── routes/                      # Route/access/navigation registry
├── features/CAPABILITY/
│   ├── pages/                   # Route-level orchestration
│   ├── components/              # Feature-owned presentation
│   ├── state/                   # Hooks, reducers, caches, polling/retry state
│   ├── utils/                   # Pure transformations and rules
│   ├── models/                  # Form/view models and API-to-UI mapping
│   └── types/                   # Feature-only UI types
├── components/                  # Cross-feature UI
├── lib/api/contracts/           # Typed endpoint modules by capability
├── lib/auth/ and lib/utils/     # Cross-feature behavior
├── types/api/                   # Split backend wire shapes by capability
└── styles/                      # Global and feature CSS bundles
```

Every feature subfolder is optional. Pages coordinate data and navigation;
detailed rendering belongs in components, workflow state in `state`, and pure
rules in `utils` or `models`.

```text
app ──> features/components/routes/lib/types
features ──> shared components/routes/lib/types
components/routes ──> lib/types
API contracts ──> shared API transport and API wire types
shared lib/types -X-> features/app
```

Do not add imports into another feature's internal components, state, or
utilities. Keep behavior with its owner, expose a small intentional public
module, or promote a genuinely shared concept. Existing sibling-feature imports
are not precedent.

### Implementing a frontend slice

1. Put pages and supporting components/state/rules under the owning feature.
2. For a routed page, update id, path, title, access classification, and
   navigation in `frontend/src/routes/routes.ts`; add an alias only to preserve
   an existing URL. Add its lazy composition in `frontend/src/app/App.tsx`.
3. Extend the existing canonical wire-type owner first, such as
   `frontend/src/types/query.ts`. For a newly split/new DTO family, use
   `frontend/src/types/api/CAPABILITY.ts` and retain the compatibility export
   from `frontend/src/types/api.ts`.
4. Extend the existing canonical endpoint owner first. For a newly split/new
   capability, use `frontend/src/lib/api/contracts/CAPABILITY.ts` and retain the
   compatibility export from `frontend/src/lib/api/contracts.ts`.
5. Add colocated `*.test.ts` or `*.test.tsx` coverage plus route/access and API
   contract tests where applicable.

Use the configured `@/` alias. Features call typed API contract modules; only
those modules may use the shared transport in `frontend/src/lib/api/client.ts`.
Do not instantiate an API client or call raw `fetch` from a feature. Encode path
identifiers with `encodeURIComponent` and query parameters with
`URLSearchParams`.

Add styles to an existing bundle or one clearly named feature bundle imported
once through `frontend/src/styles.css`. Preserve semantic HTML, keyboard access,
visible focus, sufficient contrast, reduced motion, and status communication
that does not depend on color alone.

## Configuration and dependencies

Runtime RAG configuration precedence is:

```text
saved workspace record -> environment bootstrap -> canonical Python defaults
```

The owning feature interprets behavior. `rag.core.config.Settings` is a typed
compatibility facade, not the workspace-precedence owner. Compose owns topology,
addresses, volumes, queues, and explicit environment distribution. Dockerfiles
own image construction. Neither should own mutable application-policy defaults.

Keep dependency authority singular:

- API, lightweight workers, and background processes use
  `backend/pyproject.toml` plus `backend/uv.lock`.
- The document-pipeline image uses its adjacent `pyproject.toml` and `uv.lock`.
- Backend images use `uv sync --locked --no-dev`; do not add competing
  requirements/constraints or resolve external packages with pip in Dockerfiles.
- Document-worker Torch packages remain exact CPU-index pins; adding CUDA,
  NVIDIA, or Triton requires an explicit deployment decision.
- Frontend dependencies use `package.json` plus `package-lock.json`; update and
  commit the lock when dependencies change.

## Security and reliability invariants

- Enforce document group, clearance, lifecycle, and current-version filters
  before evidence leaves vector storage; keep Qdrant ABAC payloads synchronized.
- Preserve source provenance and access context through ingestion, retrieval,
  generated artifacts, and evaluations.
- UI route gating is not authorization. Backend and service-token boundaries
  enforce permissions independently; browser mutations keep centralized CSRF.
- Do not log secrets or document content. Validate external paths, URLs,
  connector input, model output, and serialized job payloads.
- Air-gapped runtime fails clearly when required models/caches are absent; it
  never silently downloads at request or task time.

## Validation

Use Node 22 and npm 10. From the repository root:

```bash
# Reproducible setup
uv sync --project backend --locked --extra dev
npm --prefix frontend ci

# Dependency locks
uv lock --check --project backend
uv lock --check --project backend/apps/workers/document_pipeline

# Backend lint, focused tests, architecture gates, and full suite
uv run --directory backend --locked --extra dev ruff check apps src tests
uv run --directory backend --locked --extra dev python -m pytest tests/CAPABILITY
uv run --directory backend --locked --extra dev python -m pytest tests/architecture
uv run --directory backend --locked --extra dev python -m pytest tests

# Frontend
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run check:dead-code

# Repository/deployment boundaries
scripts/check_dead_code.sh
docker compose config --quiet
```

Run the smallest checks that prove the change, then broader checks for a
cross-cutting or release-boundary change. Additionally:

- Public API changes update the relevant OpenAPI contract and route tests.
- Worker changes run feature execution, worker adapter, and task-registration
  tests.
- Frontend route/permission changes run route/access and owning-feature tests.
- API client changes test method, path, encoded identifiers, payload, errors,
  and compatibility normalization.
- Configuration changes run `test_configuration_contract.py` and Compose
  validation.
- Dependency/image changes check relevant locks, build the affected image, and
  run an import/health smoke test.
- Structural changes add or update an architecture test; documentation alone is
  not an enforceable boundary.

The slice is done when ownership is clear, compatibility is preserved or
explicitly migrated, meaningful failure and retry paths are tested, affected
documentation is updated, and unrelated worktree changes remain untouched.
