# Windows Airgapped Runtime Runbook

This guide describes how to prepare and run AgenticRAG on an offline Windows
machine with Docker Desktop and a host-installed Ollama service. It intentionally
does not start vLLM yet. vLLM image and model-cache steps are included at the
end for a later GPU-backed rollout.

Run the Windows commands in PowerShell unless a command says otherwise.

## Target Architecture

- Windows runs Docker Desktop with Linux containers.
- AgenticRAG services run in Docker Compose.
- Ollama runs directly on the Windows host and already has the chat and
  embedding models installed.
- Containers reach Ollama at `http://host.docker.internal:11434`.
- Runtime model downloads are disabled with the existing airgap environment
  flags.
- vLLM services remain disabled because they are behind the `vllm` Compose
  profile.

## Prerequisites

On the offline Windows host:

- Docker Desktop is installed and switched to Linux containers.
- WSL 2 backend is enabled.
- Ollama is installed, running, and has the selected chat and embedding models.
- The project source bundle, Docker image tar, and cache-volume tar files have
  been transferred from a connected preparation machine.
- Enough disk is available for Docker images, volumes, document storage, and
  model caches. Keep at least tens of GB free even before adding vLLM.

Before disconnecting the preparation machine, download any required installers
for Docker Desktop, WSL updates, GPU drivers, Ollama, and internal security
software. Do not rely on the offline target to fetch anything at first boot.

## Preparation Flow

The repository currently documents the bundle process as explicit manual steps;
it does not ship an automated USB-bundle script. Use an `amd64` preparation
machine for most Intel/AMD Windows Docker Desktop targets, then follow the env,
image, and cache steps below in order. Use `arm64` artifacts only when the target
Windows machine is ARM64.

## Prepare the Runtime Env File

Create this file in the project root on both the connected preparation machine
and the offline Windows target. Adjust the Ollama model names to match
`ollama list` on the Windows host.

```powershell
@'
FRONTEND_PORT=3000
QDRANT_HTTP_PORT=6333
QDRANT_GRPC_PORT=6334

POSTGRES_DB=agenticrag
POSTGRES_USER=agenticrag
POSTGRES_PASSWORD=replace-with-local-postgres-password
REDIS_PASSWORD=replace-with-local-redis-password
MINIO_ACCESS_KEY=agenticrag
MINIO_SECRET_KEY=replace-with-local-minio-password
MINIO_BUCKET=agenticrag-uploads

JWT_SECRET_KEY=replace-with-local-jwt-secret
CSRF_SECRET_KEY=replace-with-local-csrf-secret
SERVICE_TOKEN=replace-with-local-service-token
DEPLOYMENT_CONTROLLER_TOKEN=replace-with-local-deployment-controller-token
BOOTSTRAP_ADMIN_EMAIL=admin@prudentia.ai
BOOTSTRAP_ADMIN_PASSWORD=replace-with-local-admin-password

RAG_MODEL_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_CHAT_MODEL=llama3.1:8b
OLLAMA_EMBED_MODEL=nomic-embed-text:latest
OLLAMA_VISION_MODEL=
OLLAMA_NUM_CTX=16384
OLLAMA_THINKING_ENABLED=false

RAG_FAITHFULNESS_POLICY=never
RAG_RETRIEVAL_TOKEN_BUDGET=12000
RAG_JSON_NUM_PREDICT=4096
RAG_SPARSE_MODEL=Qdrant/bm25
RAG_SPARSE_CACHE_DIR=/models/fastembed
RAG_RERANKER_MODEL=jinaai/jina-reranker-v1-turbo-en
RAG_RERANKER_CACHE_DIR=/models/fastembed
FASTEMBED_CACHE_HOST_DIR=./model-cache/fastembed
DOCLING_CACHE_HOST_DIR=./model-cache/docling

PREWARM_FASTEMBED=false
PREWARM_DOCLING=false
DOCLING_OCR_BACKEND=onnxruntime
DOCLING_OCR_LANGS=english

AIRGAP_RUNTIME_OFFLINE=1
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
HF_HUB_DISABLE_XET=1
DO_NOT_TRACK=1

CLAMAV_NO_FRESHCLAMD=true
CLAMAV_SCAN_ENABLED=true

VITE_API_BASE_URL=
VITE_POLLING_INTERVAL_MS=2000
'@ | Set-Content -Encoding ASCII .env.windows-airgap
```

Leave `VITE_API_BASE_URL` blank for the default same-origin setup. Users can
open the frontend at the current host IP and port, and the frontend will call
the API through that same origin.

If the airgapped deployment does not have a pre-seeded ClamAV database in the
image or through an internal update process, file uploads may fail while virus
scanning is enabled. For a pilot-only run you can set `CLAMAV_SCAN_ENABLED=false`;
for production, ship a ClamAV image that already contains the approved database
or use an internal mirror/update process.

## Build and Seed on a Connected Machine

Use a connected machine that can access Docker registries, Python packages, npm
packages, Hugging Face artifacts, and Docling artifacts. Use the same CPU
architecture as the Windows target, normally `linux/amd64`.

Set a bundle directory outside the repo:

```powershell
$Bundle = "C:\agenticrag-airgap-bundle"
New-Item -ItemType Directory -Force $Bundle | Out-Null
```

Build the project images and pull third-party runtime images:

```powershell
docker compose --env-file .env.windows-airgap pull postgres redis minio qdrant clamav
docker compose --env-file .env.windows-airgap build --pull api ingestion-worker frontend
```

Create and seed the FastEmbed sparse/reranker cache volume used for the
transfer archive:

```powershell
docker volume create agenticrag_backend-reranker-cache

docker run --rm `
  -e AIRGAP_RUNTIME_OFFLINE=0 `
  -e HF_HUB_OFFLINE=0 `
  -e TRANSFORMERS_OFFLINE=0 `
  -e HF_DATASETS_OFFLINE=0 `
  -e HF_HUB_DISABLE_XET=1 `
  -e DO_NOT_TRACK=1 `
  -e RAG_SPARSE_MODEL=Qdrant/bm25 `
  -e RAG_SPARSE_CACHE_DIR=/models/fastembed `
  -e RAG_RERANKER_MODEL=jinaai/jina-reranker-v1-turbo-en `
  -e RAG_RERANKER_CACHE_DIR=/models/fastembed `
  -v agenticrag_backend-reranker-cache:/models/fastembed `
  agenticrag-api `
  python -m rag.ops.prewarm_fastembed --all-rerankers
```

The command downloads and probes the sparse model plus every supported
cross-encoder reranker before exporting `backend-reranker-cache.tgz`.

Create and seed the shared Docling cache volume used for the transfer archive
while still online:

```powershell
docker volume create agenticrag_backend-docling-cache

docker run --rm `
  -e DOCLING_ARTIFACTS_PATH=/models/docling `
  -e DOCLING_OCR_BACKEND=onnxruntime `
  -e DOCLING_OCR_LANGS=english `
  -e AIRGAP_RUNTIME_OFFLINE=0 `
  -e HF_HUB_OFFLINE=0 `
  -e TRANSFORMERS_OFFLINE=0 `
  -e HF_DATASETS_OFFLINE=0 `
  -e HF_HUB_DISABLE_XET=1 `
  -e DO_NOT_TRACK=1 `
  -v agenticrag_backend-docling-cache:/models/docling `
  agenticrag-ingestion-worker `
  python -m rag.ingestion.ops.prewarm_docling
```

The prewarm command verifies the Docling layout/table cache and the RapidOCR OCR
files before it exits. By default the runtime OCR backend is RapidOCR on
ONNX Runtime with English OCR. Set `DOCLING_OCR_LANGS=chinese` or
`DOCLING_OCR_LANGS=english,chinese` before prewarming if the offline deployment
needs those RapidOCR files at runtime.

Export the images needed for the no-vLLM runtime:

```powershell
$Images = @(
  "postgres:16-alpine",
  "redis:7-alpine",
  "minio/minio:RELEASE.2024-07-16T23-46-41Z",
  "qdrant/qdrant:v1.12.6",
  "clamav/clamav-debian:stable",
  "agenticrag-api",
  "agenticrag-ingestion-worker",
  "agenticrag-frontend"
)

docker image save --output "$Bundle\agenticrag-runtime-images.tar" $Images
```

Export the model/cache archive volumes. The helper container uses
`postgres:16-alpine` because that image is already part of the runtime bundle
and includes `sh` and `tar`.

```powershell
$BundlePath = (Resolve-Path $Bundle).Path

docker run --rm `
  -v agenticrag_backend-reranker-cache:/from `
  -v "${BundlePath}:/bundle" `
  postgres:16-alpine `
  sh -c "cd /from && tar -czf /bundle/backend-reranker-cache.tgz ."

docker run --rm `
  -v agenticrag_backend-docling-cache:/from `
  -v "${BundlePath}:/bundle" `
  postgres:16-alpine `
  sh -c "cd /from && tar -czf /bundle/backend-docling-cache.tgz ."
```

Create a source archive. This includes committed files only; if you are
shipping uncommitted local changes, create the archive from your release process
instead.

```powershell
git archive --format=zip --prefix AgenticRAG/ --output "$Bundle\AgenticRAG-source.zip" HEAD
Copy-Item .env.windows-airgap "$Bundle\.env.windows-airgap"
```

The transfer bundle now needs at least:

- `AgenticRAG-source.zip`
- `.env.windows-airgap`
- `agenticrag-runtime-images.tar`
- `backend-reranker-cache.tgz`
- `backend-docling-cache.tgz`

## Load on the Offline Windows Host

Copy the bundle to the offline machine, for example `D:\agenticrag-airgap-bundle`.

Unpack the source:

```powershell
$Bundle = "D:\agenticrag-airgap-bundle"
$InstallRoot = "C:\AgenticRAG"

New-Item -ItemType Directory -Force $InstallRoot | Out-Null
Expand-Archive -Force "$Bundle\AgenticRAG-source.zip" $InstallRoot
Set-Location "$InstallRoot\AgenticRAG"
Copy-Item "$Bundle\.env.windows-airgap" .\.env.windows-airgap
```

Load Docker images without network access:

```powershell
docker load --input "$Bundle\agenticrag-runtime-images.tar"
docker image ls
```

Create and import the required cache folders:

```powershell
New-Item -ItemType Directory -Force .\model-cache\fastembed | Out-Null
New-Item -ItemType Directory -Force .\model-cache\docling | Out-Null
tar -xzf "$Bundle\backend-reranker-cache.tgz" -C .\model-cache\fastembed
tar -xzf "$Bundle\backend-docling-cache.tgz" -C .\model-cache\docling
```

Do not import `postgres-data`, `qdrant-data`, `minio-data`, or `redis-data` for
a fresh installation. Docker Compose will create them. Only import those data
volumes when migrating an existing deployment.

## Verify Ollama on Windows

Check the host Ollama service first:

```powershell
ollama list
Invoke-RestMethod http://localhost:11434/api/tags
```

Confirm that the model names in `.env.windows-airgap` exactly match installed
models. The chat model and embedding model are both required.

If containers cannot reach Ollama through `host.docker.internal`, configure
Ollama to listen on an address Docker Desktop can reach, then restart Ollama.
Commonly this means setting `OLLAMA_HOST=0.0.0.0:11434` at the Windows user or
system environment level. If you do that, restrict access with Windows Firewall
because Ollama should not be exposed to untrusted networks.

## Start AgenticRAG Offline

Start the no-vLLM stack:

```powershell
docker compose --env-file .env.windows-airgap up -d --no-build --pull never --wait
```

The frontend is available at:

```text
http://localhost:3000
```

The API is available through the frontend reverse proxy at:

```text
http://localhost:3000/api/v1
```

Useful checks:

```powershell
docker compose --env-file .env.windows-airgap ps
Invoke-RestMethod http://localhost:3000/healthz
docker compose --env-file .env.windows-airgap exec api `
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=8)"
docker compose --env-file .env.windows-airgap logs --tail 100 api
docker compose --env-file .env.windows-airgap logs --tail 100 ingestion-worker
```

Check container-to-host Ollama connectivity after the API is running:

```powershell
docker compose --env-file .env.windows-airgap exec api `
  python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=5).read().decode()[:1000])"
```

If the application was previously run with persisted Postgres data and the
workspace settings were saved with provider `vllm`, use the admin settings page
to switch the workspace provider back to `ollama`, or start from fresh
`postgres-data`.

## Storage Inventory

These cache folders are expected in the project directory:

- `model-cache/fastembed`: FastEmbed sparse model and reranker cache.
  Required for offline retrieval/reranking.
- `model-cache/docling`: Docling model/artifact cache. Required for offline
  Docling parsing.

These named volumes are also expected:

- `agenticrag_postgres-data`: application database.
- `agenticrag_qdrant-data`: vector database.
- `agenticrag_minio-data`: uploaded source documents and generated artifacts.
- `agenticrag_redis-data`: Redis append-only data.
- `agenticrag_vllm-model-cache`: vLLM Hugging Face model cache. Not needed until
  the vLLM profile is enabled.

Do not run `docker compose down -v` unless you intentionally want to delete
application data and caches.

## Updating an Offline Host

Prepare a new bundle on a connected machine using the same process, then on the
offline host:

```powershell
docker compose --env-file .env.windows-airgap down
docker load --input "$Bundle\agenticrag-runtime-images.tar"
```

Replace the source directory with the new release source, keep `.env.windows-airgap`,
and start again:

```powershell
docker compose --env-file .env.windows-airgap up -d --no-build --pull never --wait
```

Do not delete the data volumes unless the update requires a clean install.

## Adding vLLM Later

Do not enable this for the current Ollama-only deployment. Compose only starts
vLLM services when the `vllm` profile is explicitly enabled.

When you are ready to prepare vLLM, build a separate connected bundle that adds:

- `vllm/vllm-openai:latest`
- `agenticrag_vllm-model-cache` exported as `vllm-model-cache.tgz`
- Hugging Face files for the models configured in `docker-compose.yml`:
  - `Qwen/Qwen3-8B-AWQ`
  - `nomic-ai/nomic-embed-text-v1.5`
  - `Qwen/Qwen2.5-VL-7B-Instruct-AWQ`, only if vision is needed

On the connected GPU staging machine, temporarily allow Hugging Face downloads
for the vLLM services and start the profile once to fill the cache:

```powershell
docker compose --env-file .env.windows-airgap --profile vllm pull vllm-text vllm-embeddings vllm-vision

$env:AIRGAP_RUNTIME_OFFLINE = "0"
$env:HF_HUB_OFFLINE = "0"
$env:TRANSFORMERS_OFFLINE = "0"
$env:HF_DATASETS_OFFLINE = "0"
docker compose --env-file .env.windows-airgap --profile vllm up -d vllm-text vllm-embeddings
```

Add `vllm-vision` to the `up` command only when preparing the vision model too.

After the services have fully loaded once, stop them and export the vLLM image
and cache:

```powershell
docker compose --env-file .env.windows-airgap --profile vllm down
docker image save --output "$Bundle\agenticrag-vllm-image.tar" vllm/vllm-openai:latest

$BundlePath = (Resolve-Path $Bundle).Path

docker run --rm `
  -v agenticrag_vllm-model-cache:/from `
  -v "${BundlePath}:/bundle" `
  postgres:16-alpine `
  sh -c "cd /from && tar -czf /bundle/vllm-model-cache.tgz ."
```

On the offline Windows host, load the vLLM image, import the cache into
`agenticrag_vllm-model-cache`, verify Docker Desktop GPU support, then start:

```powershell
docker compose --env-file .env.windows-airgap --profile vllm up -d --no-build --pull never vllm-text vllm-embeddings
```

Add `vllm-vision` here only if the vision cache was prepared and the machine has
enough GPU memory.

Only after those endpoints are healthy should you change `RAG_MODEL_PROVIDER` to
`vllm` or switch provider in the application settings. Recreate the API and
workers after changing provider settings:

```powershell
docker compose --env-file .env.windows-airgap up -d --no-build --pull never --force-recreate `
  api ingestion-worker artifact-worker evaluation-worker folder-scheduler ingest-maintenance
```

The `deployment-controller` service is profile-gated with `vllm` and is present
only for later vLLM apply/recreate actions. It uses its own minimal image and the
dedicated `DEPLOYMENT_CONTROLLER_TOKEN`; keep that value identical in the API
and controller environments. On Windows, its Docker CLI bind mounts may need
adjustment before using the in-app vLLM deployment controls. The Ollama-only
path does not require those controls.

## Troubleshooting

If Compose tries to build or pull on the offline host, stop and check that all
runtime images were loaded. Always use `--no-build --pull never` offline.

If the API starts but chat or ingestion fails, verify these first:

- `RAG_MODEL_PROVIDER=ollama`
- `OLLAMA_BASE_URL=http://host.docker.internal:11434`
- `OLLAMA_CHAT_MODEL` exists in `ollama list`
- `OLLAMA_EMBED_MODEL` exists in `ollama list`
- container-to-host Ollama connectivity works from the `api` container
- `model-cache/fastembed` and `model-cache/docling` were imported before the
  first full start

If PDF ingestion fails in offline mode, inspect the ingestion logs and confirm
that Docling and OCR artifacts verify successfully:

```powershell
docker compose --env-file .env.windows-airgap exec ingestion-worker `
  python -m rag.ingestion.ops.prewarm_docling --verify-only
```

If reranking fails, confirm the FastEmbed cache folder is not empty:

```powershell
docker compose --env-file .env.windows-airgap exec api `
  python -m rag.ops.prewarm_fastembed --verify-only --all-rerankers
```

## References

- Docker Desktop Windows install and WSL 2 requirements:
  https://docs.docker.com/desktop/setup/install/windows-install/
- Docker Compose profiles:
  https://docs.docker.com/compose/how-tos/profiles/
- Docker image save:
  https://docs.docker.com/reference/cli/docker/image/save/
- Docker image load:
  https://docs.docker.com/reference/cli/docker/image/load/
- Docker Desktop GPU support for later vLLM work:
  https://docs.docker.com/desktop/features/gpu/
