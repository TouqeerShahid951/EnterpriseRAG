# Windows Air-Gapped In-Place Upgrade Plan

## Purpose

Upgrade the existing Windows Docker deployment with newly built application
images while preserving all users, documents, metadata, vectors, graph data,
jobs, settings, and stored files.

This is a backup-first plan, not a clean-install procedure. The existing
Windows deployment is the source of truth for data and secrets. The connected
Mac is used only to build signed-off `linux/amd64` release artifacts.

## Core deployment decision

Perform the first upgrade as an **application-only upgrade**:

- Replace the API, ingestion-worker, and frontend images.
- Keep the Windows host's currently running PostgreSQL, Redis, MinIO, Qdrant,
  Neo4j, and ClamAV image versions unchanged unless the new application proves
  that a specific infrastructure upgrade is required.
- Reuse the exact existing named volumes by explicit volume name. Do not rely
  only on the source directory name or a presumed Compose project name.
- Reuse the target's existing environment file and secrets. Merge new keys
  into it; never replace it with a generated environment file.
- Rehearse the upgrade on restored clone volumes before starting the new API
  against production data.

Infrastructure upgrades, embedding-model changes, and document reindexing are
separate maintenance events. Combining them with this release would make
failure diagnosis and rollback unnecessarily risky.

## Non-negotiable safety rules

1. Never run `docker compose down -v`, `docker volume prune`, or delete a volume
   during an upgrade.
2. Do not start the new API until the pre-upgrade backup has been checksummed
   and restored successfully into a rehearsal stack. API startup automatically
   changes the PostgreSQL schema.
3. Do not assume the old project is named `agenticrag`. Discover the project
   label and actual mounts from the running containers.
4. Do not change the embedding provider, embedding model, Qdrant collection,
   MinIO bucket, or object-storage backend during the initial upgrade.
5. Do not copy target secrets or target documents back to the connected build
   machine. Keep backups inside the air-gapped environment.
6. Do not build the release from an uncommitted worktree. A release must map to
   one reviewed commit/tag and one image manifest.
7. All transferred images must be `linux/amd64` unless the Windows Docker
   engine explicitly reports another architecture.

## What must be preserved

| Store | Current Compose location | Authoritative contents |
| --- | --- | --- |
| PostgreSQL | `postgres-data` at `/var/lib/postgresql/data` | Users and password hashes, groups, document metadata, ingest/review jobs, audit history, chat history, connectors, workspace settings, evaluations, and artifact metadata |
| MinIO | `minio-data` at `/data` | Raw uploaded documents, processed image assets, and generated artifacts when `UPLOAD_STORAGE_BACKEND=minio` |
| Qdrant | `qdrant-data` at `/qdrant/storage` | Document chunks, dense/sparse vectors, payloads, and GraphRAG community-summary vectors |
| Neo4j | `neo4j-data` at `/data` | GraphRAG entities and relationships |
| Redis | `redis-data` at `/data` | Celery queues, refresh sessions, query-session memory, and GraphRAG checkpoints |
| Local uploads | `local-upload-data` at `UPLOAD_STORAGE_DIR` | Files stored locally instead of in MinIO, plus locally stored artifacts |
| Folder sources | Host bind `FOLDER_SOURCES_HOST_DIR` | Operator-managed source files for scheduled folder ingestion |
| Model caches | Host binds for FastEmbed, Docling, and optional vLLM | Reconstructable, but required for offline startup and ingestion |

PostgreSQL, MinIO, Qdrant, and Neo4j form one logical data set. PostgreSQL
records refer to MinIO object paths and document IDs represented in Qdrant and
Neo4j. Back them up at the same quiesced point in time.

## Phase 0: release and target discovery gates

Do not schedule the production change until this worksheet is complete.

### Connected Mac

- Release commit/tag:
- `git status --porcelain` is empty: yes/no
- Docker buildx supports `linux/amd64`: yes/no
- Unit/integration test result:
- API image tag and digest:
- Ingestion image tag and digest:
- Frontend image tag and digest:
- Bundle SHA-256:

### Air-gapped Windows host

- Docker engine architecture:
- Docker Desktop/Engine version:
- Docker Compose version:
- Existing Compose project label:
- Existing compose/config directory:
- Existing environment-file path and SHA-256:
- Free disk space:
- Current application image IDs/tags:
- PostgreSQL image/version and actual volume name:
- Redis image/version and actual volume name:
- MinIO image/version and actual volume name:
- Qdrant image/version and actual volume name:
- Neo4j image/version and actual volume name:
- Local-upload actual volume name, if any:
- `UPLOAD_STORAGE_BACKEND` and `UPLOAD_STORAGE_DIR`:
- `FOLDER_SOURCES_HOST_DIR`:
- FastEmbed/Docling/vLLM cache paths:
- Embedding provider and model:
- Qdrant collection names:
- Ollama or vLLM model names:

Useful read-only discovery commands on Windows:

```powershell
docker version
docker compose version
docker info --format '{{.Architecture}}'
docker compose ls --all
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker volume ls
```

For each existing container, capture its Compose project and mounts:

```powershell
$Container = '<existing-postgres-container-name-or-id>'
docker inspect $Container --format `
  '{{ index .Config.Labels "com.docker.compose.project" }}'
docker inspect $Container --format `
  '{{range .Mounts}}{{println .Type .Name .Source "->" .Destination}}{{end}}'
docker inspect $Container --format `
  '{{.Config.Image}} {{.Image}}'
```

Use the same inspection for MinIO, Qdrant, Neo4j, Redis, API, and ingestion.
Record actual values; names in this document are not a substitute for target
inspection.

### Special check for legacy local uploads

Before recreating the old API container, inspect its configured
`UPLOAD_STORAGE_BACKEND` and `UPLOAD_STORAGE_DIR`. If it used local storage but
that directory was not mounted from a named volume or host path, files may
exist only in the old container's writable layer. Copy that directory out with
`docker cp` before removing the container.

## Phase 1: create a reproducible AMD64 release on the connected Mac

The current build host is Apple Silicon. Normal local builds are ARM64 and are
not suitable for a typical Intel/AMD Windows Docker host.

### 1. Freeze the source

Choose a release ID that includes a version and commit, for example:

```bash
export RELEASE=2026.07.11-b98ad49a
test -z "$(git status --porcelain)"
git rev-parse HEAD
```

The release gate must fail while the worktree is dirty. Commit or intentionally
exclude work before building; do not use a source archive from `HEAD` while
building images from different uncommitted files.

### 2. Build uniquely tagged application images

Keep `VITE_API_BASE_URL` blank. The frontend nginx container proxies `/api/` to
the internal API services; port 8000 is not published on the host.

```bash
docker buildx build \
  --platform linux/amd64 \
  --file backend/apps/api/Dockerfile \
  --tag "agenticrag-api:${RELEASE}" \
  --load \
  backend

docker buildx build \
  --platform linux/amd64 \
  --file backend/apps/ingestion/Dockerfile \
  --tag "agenticrag-ingestion-worker:${RELEASE}" \
  --build-arg PREWARM_FASTEMBED=false \
  --build-arg PREWARM_DOCLING=false \
  --load \
  backend

docker buildx build \
  --platform linux/amd64 \
  --file frontend/Dockerfile \
  --tag "agenticrag-frontend:${RELEASE}" \
  --build-arg VITE_API_BASE_URL= \
  --build-arg VITE_POLLING_INTERVAL_MS=2000 \
  --load \
  frontend
```

Run image smoke tests under `--platform linux/amd64` and inspect the resulting
platform before export.

### 3. Use a release Compose override

Create a reviewed release override that assigns the versioned API image to
`api`, `query-api`, all API workers, and maintenance services; the versioned
ingestion image to both ingestion workers; and the versioned frontend image to
`frontend`.

The same target-specific override must pin infrastructure services to the
image references captured from the existing Windows deployment. It must also
declare each persistent volume as external with its captured name, for example:

```yaml
services:
  api:
    image: agenticrag-api:${AGENTICRAG_RELEASE}
  query-api:
    image: agenticrag-api:${AGENTICRAG_RELEASE}
  ingestion-worker:
    image: agenticrag-ingestion-worker:${AGENTICRAG_RELEASE}
  graphrag-worker:
    image: agenticrag-ingestion-worker:${AGENTICRAG_RELEASE}
  frontend:
    image: agenticrag-frontend:${AGENTICRAG_RELEASE}

volumes:
  postgres-data:
    external: true
    name: ${POSTGRES_VOLUME_NAME}
  qdrant-data:
    external: true
    name: ${QDRANT_VOLUME_NAME}
```

Include every API-based service and all six named volumes in the real override.
External declarations make Compose fail on a wrong/missing volume name instead
of silently creating an empty database.

### 4. Prepare offline model caches

Compare the release's FastEmbed, reranker, Docling, and OCR requirements with
the target's existing caches. Prewarm missing artifacts while connected, then
verify them in offline mode. Model files are release dependencies, not business
data; install them beside the old caches so rollback remains possible.

Do not change the target's active embedding model during this upgrade. A model
change requires a separate collection and controlled reindex.

### 5. Export the transfer bundle

The bundle should contain:

- The three versioned application images for `linux/amd64`.
- Exact third-party images only when target discovery shows one is missing or a
  tested infrastructure change is required.
- Base Compose plus the reviewed release/volume override.
- A non-secret environment-delta template containing only newly introduced
  keys and explanations.
- FastEmbed/Docling cache archives needed by the release.
- `image-list.txt`, image IDs/digests, release commit, build timestamp, and test
  results.
- `SHA256SUMS` covering every transferred artifact.
- This plan and the final execution checklist.

Example image export:

```bash
printf '%s\n' \
  "agenticrag-api:${RELEASE}" \
  "agenticrag-ingestion-worker:${RELEASE}" \
  "agenticrag-frontend:${RELEASE}" \
  > image-list.txt

docker image save --platform linux/amd64 \
  --output agenticrag-app-images-linux-amd64.tar \
  "agenticrag-api:${RELEASE}" \
  "agenticrag-ingestion-worker:${RELEASE}" \
  "agenticrag-frontend:${RELEASE}"

shasum -a 256 agenticrag-app-images-linux-amd64.tar > SHA256SUMS
```

Do not put the Windows target's environment file, secrets, database dumps, or
documents in the connected-machine bundle.

## Phase 2: quiesce and back up the Windows deployment

### 1. Establish a baseline

Record before-upgrade counts and a small set of known-good functional checks:

- Active users and total users.
- Current/non-deleted documents.
- Ingest jobs by status.
- Every Qdrant collection and point count.
- MinIO bucket/object count and size.
- Neo4j node and relationship counts.
- Redis persistence status.
- A successful login, download of a known document, and answer to a known query.

Also save the old application images to a target-local rollback archive before
loading or retagging anything.

### 2. Preserve configuration

Copy the existing environment file, Compose files/overrides, source/config
directory, folder sources, model caches, and any TLS certificates into a
timestamped backup directory on the air-gapped host. Record SHA-256 hashes.

At minimum, preserve these values exactly:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `DATABASE_URL`
- `REDIS_PASSWORD`, `REDIS_URL`, and `CELERY_BROKER_URL`
- `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, and `MINIO_BUCKET`
- `NEO4J_USER`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE`
- `JWT_SECRET_KEY`, `CSRF_SECRET_KEY`, and `SERVICE_TOKEN`
- `CONNECTOR_SECRETS_KEY` and `CONNECTOR_SECRETS_KEY_RING`
- `UPLOAD_STORAGE_BACKEND` and `UPLOAD_STORAGE_DIR`
- Qdrant collection names and every provider/model setting
- Host bind paths, ports, CORS origins, and cookie settings

`POSTGRES_PASSWORD` alone does not update the password inside an initialized
PostgreSQL volume. The explicit `DATABASE_URL` must still match the existing
database. The same principle applies to Redis/Celery URLs. Changing
`CONNECTOR_SECRETS_KEY` can make saved connector credentials undecryptable.

### 3. Drain work and stop writers

Begin a maintenance window, stop new intake and schedulers, and let active
ingestion/artifact/evaluation jobs finish. Confirm that no jobs are processing
before stopping application services.

Take an additional PostgreSQL custom-format logical dump while PostgreSQL is
healthy. This is portable across volume layouts and is required if PostgreSQL
major versions ever change.

```powershell
$Pg = '<existing-postgres-container-name-or-id>'
docker exec $Pg sh -lc `
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/agenticrag.dump'
docker cp "${Pg}:/tmp/agenticrag.dump" `
  'D:\AgenticRAG\backups\<timestamp>\agenticrag.dump'
```

Then stop the full stack without removing containers or volumes. A stopped,
cold volume archive gives all stores a consistent recovery point.

### 4. Archive every actual named volume

Use the names discovered from container mounts, not assumed names. The helper
image only needs `sh` and `tar` and must already exist on the offline host.

```powershell
$BackupDir = 'D:\AgenticRAG\backups\<timestamp>'
$HelperImage = '<already-installed-alpine-based-image>'
$Volumes = @(
  '<actual-postgres-volume>',
  '<actual-qdrant-volume>',
  '<actual-minio-volume>',
  '<actual-neo4j-volume>',
  '<actual-redis-volume>',
  '<actual-local-upload-volume>'
)

foreach ($Volume in $Volumes) {
  if (-not $Volume) { continue }
  docker volume inspect $Volume *> $null
  if ($LASTEXITCODE -eq 0) {
    docker run --rm --user 0:0 --entrypoint sh `
      -v "${Volume}:/from:ro" `
      -v "${BackupDir}:/backup" `
      $HelperImage `
      -c "cd /from && tar -czf /backup/${Volume}.tgz ."
    if ($LASTEXITCODE -ne 0) { throw "Backup failed: $Volume" }
  }
}
```

Archive the folder-source and cache bind directories separately. Generate
SHA-256 hashes and confirm that every archive is non-empty. Keep at least two
copies on separate approved offline media.

Native backups are also recommended: Qdrant snapshots for every collection and
an offline Neo4j database dump. Raw cold-volume archives remain the full-stack
rollback source because they preserve one quiesced point in time.

## Phase 3: mandatory rehearsal on cloned volumes

Use the backup archives to create a second isolated Compose project on the same
Windows Docker engine, subject to available disk space:

1. Create rehearsal volumes with a distinct prefix.
2. Restore all six cold archives into those volumes.
3. Use a rehearsal override that explicitly maps those clone volumes.
4. Use different host ports for frontend, Qdrant, and Neo4j.
5. Keep the production stack stopped or keep all rehearsal ports/networks fully
   isolated.
6. Start the existing infrastructure image versions against the cloned data.
7. Start only the new API. Its startup runs PostgreSQL schema bootstrap and
   migrations.
8. Review migration logs and compare all baseline counts.
9. Start query API and frontend; test login, document listing/download, a known
   grounded query, connector-secret access, and role/permission behavior.
10. Start workers; ingest and delete a disposable test document and verify
    Qdrant, MinIO/local storage, PostgreSQL, and Neo4j behavior.
11. Stop and restart the rehearsal stack to validate persistence and offline
    startup.
12. Perform a rehearsal rollback from the backup archives.

Production is a no-go if the restore rehearsal fails, if counts unexpectedly
change, if a connector secret cannot be decrypted, or if the release tries to
download a model at runtime.

## Phase 4: production upgrade

1. Verify bundle SHA-256 hashes on Windows.
2. Load the uniquely tagged AMD64 application images. Do not overwrite the old
   tags.
3. Verify that all loaded images report `linux/amd64`.
4. Install the release into a versioned directory. Keep target data, environment
   configuration, folder sources, and model caches outside the release source
   directory where practical.
5. Copy the old target environment file into the protected configuration
   location. Merge only reviewed new keys; preserve all existing values.
6. Validate the combined Compose configuration and confirm that the resolved
   images and external volume names exactly match the approved manifest.
7. Start existing infrastructure services only, using their old image versions.
8. Start the new API alone and review its migration/startup log.
9. Re-run PostgreSQL counts before proceeding.
10. Start query API and frontend; complete login, document, and known-query smoke
    tests.
11. Start ingestion, GraphRAG, artifact, evaluation, scheduler, and maintenance
    services.
12. Compare all pre/post counts and complete the acceptance checklist.

All offline starts must use both `--no-build` and `--pull never`, with the base
and approved release overrides supplied explicitly.

## Data-engine compatibility gates

- **PostgreSQL:** Reuse a raw data volume only with the same major version. A
  major-version change requires logical dump/restore or `pg_upgrade` and is not
  part of the initial application upgrade.
- **Qdrant:** Do not downgrade. If the installed version is several minor
  versions behind the desired version, apply required intermediate minor
  upgrades separately. Keep the existing Qdrant version for the first app
  upgrade whenever compatible.
- **Neo4j:** Keep the installed 5.x image for the first app upgrade. Treat a
  store upgrade as forward-only until an offline dump/restore has been tested.
- **MinIO and Redis:** Keep existing versions for the first app upgrade. Upgrade
  them independently with their own backup/restore tests.
- **Embeddings:** Preserve provider, model, dimensions, and collection. A model
  change requires a new collection or a deliberate full reindex and is never an
  incidental deployment step.

## Rollback plan

There are two rollback levels:

### Before the new API starts

No application migration has run. Point the release override back to the old
versioned application images, restore the old configuration/source selection,
and start the old stack against the unchanged volumes.

### After the new API starts

Assume PostgreSQL has changed. An image-only rollback is not sufficient.

1. Stop the new stack.
2. Preserve the failed-upgrade volumes for investigation; do not overwrite them.
3. Create clean replacement volumes using the old actual names, or explicitly
   remap the old stack to restored volumes.
4. Restore all six pre-upgrade cold archives as one consistency set.
5. Restore the old bind directories, environment, Compose files, and application
   images.
6. Start the old infrastructure and old application.
7. Compare counts and repeat the pre-upgrade functional baseline.

The maintenance window is complete only after either the upgraded system or the
restored old system passes the acceptance checks.

## Acceptance checklist

- All expected containers are healthy and remain healthy after a Docker Desktop
  restart.
- User count matches; existing users can log in with existing passwords and
  roles.
- Document count matches; a known original file and processed image can be
  opened/downloaded.
- All Qdrant collections exist with expected point counts and vector schema.
- Neo4j node/relationship counts are unchanged or change only as explicitly
  expected by tested GraphRAG work.
- MinIO/local object counts and representative checksums match.
- A known query returns grounded citations from previously ingested documents.
- A disposable new document can be ingested, queried, and deleted.
- Connector credentials decrypt and a permitted connector test succeeds.
- Ingest, artifact, evaluation, and GraphRAG queues process successfully.
- No service attempts an external download; the host's network controls still
  enforce the air gap.
- Backup archives, old image archive, environment, and rollback instructions
  remain retained after sign-off.

## Repository work still required before execution

- Add a fresh release Compose override with versioned application image tags and
  explicit external volume names.
- Add a non-secret environment-delta template; do not generate replacement
  deployment secrets.
- Add new backup, restore, bundle, and verification tooling only after the
  target inventory and rehearsal commands have been reviewed.
- Update or retire the legacy Windows air-gap documents so they no longer point
  to removed scripts or omit Neo4j/local-upload storage.
- Add a release gate that rejects a dirty worktree, validates every image as
  `linux/amd64`, verifies offline model caches, and emits `SHA256SUMS`.
