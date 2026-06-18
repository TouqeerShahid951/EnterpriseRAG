#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLE_DIR="${BUNDLE_DIR:-/tmp/agenticrag-airgap-bundle}"
ENV_FILE=""
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agenticrag}"
PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"
SKIP_BUILD=0

usage() {
  echo "Usage: $0 [--bundle-dir PATH] [--env-file PATH] [--platform linux/amd64] [--skip-build]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bundle-dir) BUNDLE_DIR="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "$BUNDLE_DIR"
BUNDLE_DIR="$(cd "$BUNDLE_DIR" && pwd)"

secret() {
  if [ -r /proc/sys/kernel/random/uuid ]; then
    tr -d '-' < /proc/sys/kernel/random/uuid
  else
    date +%s%N
  fi
}

write_default_env() {
  local path="$1"
  local pg redis minio jwt csrf service admin
  pg="$(secret)"; redis="$(secret)"; minio="$(secret)"
  jwt="$(secret)$(secret)"; csrf="$(secret)$(secret)"
  service="$(secret)$(secret)"; admin="ChangeMe-$(secret)"
  cat > "$path" <<EOF
API_PORT=8000
FRONTEND_PORT=3000
QDRANT_HTTP_PORT=6333
QDRANT_GRPC_PORT=6334
POSTGRES_DB=agenticrag
POSTGRES_USER=agenticrag
POSTGRES_PASSWORD=$pg
REDIS_PASSWORD=$redis
MINIO_ACCESS_KEY=agenticrag
MINIO_SECRET_KEY=$minio
MINIO_BUCKET=agenticrag-uploads
JWT_SECRET_KEY=$jwt
CSRF_SECRET_KEY=$csrf
SERVICE_TOKEN=$service
BOOTSTRAP_ADMIN_EMAIL=admin@faham.ai
BOOTSTRAP_ADMIN_PASSWORD=$admin
RAG_MODEL_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_CHAT_MODEL=${OLLAMA_CHAT_MODEL:-llama3.1:8b}
OLLAMA_EMBED_MODEL=${OLLAMA_EMBED_MODEL:-nomic-embed-text:latest}
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
CLAMAV_SCAN_ENABLED=false
VITE_API_BASE_URL=http://localhost:8000
VITE_POLLING_INTERVAL_MS=2000
EOF
}

if [ -z "$ENV_FILE" ]; then
  ENV_FILE="$BUNDLE_DIR/.env.windows-airgap"
  [ -f "$ENV_FILE" ] || write_default_env "$ENV_FILE"
else
  cp "$ENV_FILE" "$BUNDLE_DIR/.env.windows-airgap"
  ENV_FILE="$BUNDLE_DIR/.env.windows-airgap"
fi

compose() {
  docker compose --env-file "$ENV_FILE" "$@"
}

env_value() {
  local key="$1"
  local default="$2"
  local value
  value="$(
    awk -F= -v key="$key" '
      /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
      {
        name=$1
        gsub(/^[ \t]+|[ \t]+$/, "", name)
        if (name == key) {
          value=substr($0, index($0, "=") + 1)
          gsub(/^[ \t]+|[ \t]+$/, "", value)
          print value
          exit
        }
      }
    ' "$ENV_FILE"
  )"
  if [ -n "$value" ]; then
    printf "%s" "$value"
  else
    printf "%s" "$default"
  fi
}

cd "$ROOT_DIR"
export DOCKER_DEFAULT_PLATFORM="$PLATFORM"
if [ "$SKIP_BUILD" -eq 0 ]; then
  if ! compose pull postgres redis minio qdrant clamav; then
    echo "Warning: some third-party image pulls failed; continuing with locally cached images." >&2
  fi
  PREWARM_FASTEMBED=false compose build --pull api ingestion-worker frontend
fi

reranker_volume="${PROJECT_NAME}_backend-reranker-cache"
docling_volume="${PROJECT_NAME}_backend-docling-cache"
docker volume create "$reranker_volume" >/dev/null
docker volume create "$docling_volume" >/dev/null

sparse_model="$(env_value RAG_SPARSE_MODEL "Qdrant/bm25")"
reranker_model="$(env_value RAG_RERANKER_MODEL "jinaai/jina-reranker-v1-turbo-en")"
docling_ocr_backend="$(env_value DOCLING_OCR_BACKEND "onnxruntime")"
docling_ocr_langs="$(env_value DOCLING_OCR_LANGS "english")"

docker run --rm \
  --platform "$PLATFORM" \
  -e AIRGAP_RUNTIME_OFFLINE=0 -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
  -e HF_DATASETS_OFFLINE=0 -e HF_HUB_DISABLE_XET=1 -e DO_NOT_TRACK=1 \
  -e RAG_SPARSE_MODEL="$sparse_model" \
  -e RAG_SPARSE_CACHE_DIR=/cache \
  -e RAG_RERANKER_MODEL="$reranker_model" \
  -e RAG_RERANKER_CACHE_DIR=/cache \
  -v "$reranker_volume:/cache" agenticrag-api \
  python -m rag.ops.prewarm_fastembed --all-rerankers

docker run --rm \
  --platform "$PLATFORM" \
  -e DOCLING_ARTIFACTS_PATH=/cache -e AIRGAP_RUNTIME_OFFLINE=0 \
  -e DOCLING_OCR_BACKEND="$docling_ocr_backend" \
  -e DOCLING_OCR_LANGS="$docling_ocr_langs" \
  -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 -e HF_DATASETS_OFFLINE=0 \
  -e HF_HUB_DISABLE_XET=1 -e DO_NOT_TRACK=1 \
  -v "$docling_volume:/cache" agenticrag-ingestion-worker \
  python -m rag_ingestion.ops.prewarm_docling --output-dir /cache

mapfile -t images < <(compose config --images | sort -u)
printf "%s\n" "${images[@]}" > "$BUNDLE_DIR/image-list.txt"
echo "$PLATFORM" > "$BUNDLE_DIR/platform.txt"
docker image save --output "$BUNDLE_DIR/agenticrag-runtime-images.tar" "${images[@]}"

for volume in backend-reranker-cache backend-docling-cache; do
  docker run --rm \
    --platform "$PLATFORM" \
    -v "${PROJECT_NAME}_${volume}:/from" \
    -v "$BUNDLE_DIR:/bundle" \
    postgres:16-alpine \
    sh -c "cd /from && tar -czf /bundle/${volume}.tgz ."
done

root_name="$(basename "$ROOT_DIR")"
tar -czf "$BUNDLE_DIR/AgenticRAG-source.tgz" \
  -C "$(dirname "$ROOT_DIR")" \
  --exclude="$root_name/.git" \
  --exclude="*/.venv" \
  --exclude="*/venv" \
  --exclude="*/__pycache__" \
  --exclude="*.pyc" \
  --exclude="*.pptx" \
  --exclude=".~lock.*" \
  --exclude="$root_name/airgap-bundle" \
  --exclude="$root_name/model-cache" \
  --exclude="$root_name/frontend/node_modules" \
  --exclude="$root_name/frontend/dist" \
  --exclude="$root_name/backend/.pytest_cache" \
  "$root_name"

cp "$ROOT_DIR/scripts/airgap/deploy_windows.ps1" "$BUNDLE_DIR/deploy_windows.ps1"
cp "$ROOT_DIR/docs/windows-airgap-runbook.md" "$BUNDLE_DIR/windows-airgap-runbook.md"

echo "Bundle ready: $BUNDLE_DIR"
du -sh "$BUNDLE_DIR"
