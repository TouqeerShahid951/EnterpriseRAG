# AgenticRAG backend

The backend is a Python modular monolith. It uses the standard `src` layout so
local tests and production run the same installable package rather than importing
code accidentally from the repository root.

## Layout

- `apps/` contains thin process entrypoints, such as FastAPI and Celery startup.
- `src/rag/` contains application code organized by product capability.
- `tests/` contains capability-aligned unit, integration, and contract tests.
- `pyproject.toml` and `uv.lock` define the installable backend environment.

The `src` directory is not a Python package and must not contain an
`__init__.py`. Import application code through `rag`, for example
`rag.ingestion.contracts`.

## Boundaries

- Keep business behavior in `src/rag`, not in `apps` entrypoints.
- Keep feature-specific contracts, services, persistence, and tests with their
  owning capability.
- Access another capability through its public service or contract rather than
  importing private implementation details.
- Keep `rag.shared` small and limited to genuinely cross-capability code.
- Add abstractions and subdirectories only when current complexity justifies
  them.

The ingestion package has a more detailed ownership map in
[`src/rag/ingestion/README.md`](src/rag/ingestion/README.md).

## Development checks

From this directory:

```bash
uv sync --extra dev
.venv/bin/python -m pytest tests
```

From the repository root, validate deployment wiring with:

```bash
docker compose config --quiet
docker compose build ingestion-worker
```

## Ingestion lease rollout

Ingestion attempts use a per-run token to fence callbacks from stale workers.
Deploy the backend before the ingestion workers: backend startup applies the
nullable `ingest_jobs.run_token` migration and accepts both legacy tokenless
leases and token-aware leases. Repository updates compare the exact stored
lease value, including `NULL`, so an older worker cannot mutate a job after a
token-aware worker has reclaimed it. After the backend is healthy, roll the
ingestion workers so new attempts start using tokens.
