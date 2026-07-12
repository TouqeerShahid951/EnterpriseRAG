# Prudentia AI / AgenticRAG

Prudentia AI is a local enterprise RAG workspace for governed document intake,
grounded retrieval, evidence review, auditability, evaluation, and artifact
generation. The repository is a modular backend, a React frontend, and a local
Docker Compose deployment.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `backend/` | FastAPI API, workers, background processes, deployment controller, feature code, and backend tests. |
| `frontend/` | React/Vite browser application and frontend tests. |
| `docs/` | Architecture, operator/user documentation, generated manuals, and design handoff material. |
| `infra/` | Runtime initialization or recovery files mounted by infrastructure containers. |
| `scripts/` | Repository-level validation and documentation builders. |
| `folder-sources/` | Local folder-ingestion mount point; contents are intentionally ignored. |
| `model-cache/` | Ignored local model artifacts required for offline execution. |
| `backups/` | Ignored local runtime recovery data; manage it with an explicit retention policy. |
| `docker-compose.yml` | Complete local deployment topology. |

`model-cache/`, `tmp/`, build outputs, local virtual environments, dependency
installs, and runtime backups are not source code and are intentionally ignored.
Do not commit `.env`; start from [`.env.example`](.env.example).

## Documentation

- [System architecture](design.md)
- [Product principles](PRODUCT.md)
- [Backend architecture](backend/README.md)
- [User guide](docs/user-guide.md)
- [Operator and role manuals](docs/manuals/README.md)
- [Windows air-gapped runbook](docs/windows-airgap-runbook.md)
- [Design handoff](docs/design-handoff/frontend-redesign-prompt.md)

## Validation

Run the primary repository checks from the repository root:

```bash
uv run --project backend ruff check backend/apps backend/src backend/tests
uv run --project backend pytest backend/tests
npm --prefix frontend run typecheck
scripts/check_dead_code.sh
docker compose config --quiet
```

Deployment-specific build and startup instructions are maintained in the
operator manuals and air-gapped runbook rather than duplicated here.
