# Airgap Runtime Mode

AgenticRAG runtime containers default to offline model loading. Runtime code should fail fast when a required model or artifact is missing instead of downloading it.

For the full Windows airgapped deployment flow using host-installed Ollama and
skipping vLLM initially, see [Windows Airgapped Runtime Runbook](windows-airgap-runbook.md).

## Runtime Defaults

The Compose stack sets these flags for API, workers, ingestion, artifact sandbox, and vLLM services:

- `AIRGAP_RUNTIME_OFFLINE=1`
- `HF_HUB_OFFLINE=1`
- `TRANSFORMERS_OFFLINE=1`
- `HF_DATASETS_OFFLINE=1`
- `HF_HUB_DISABLE_TELEMETRY=1`
- `HF_HUB_DISABLE_XET=1`
- `DO_NOT_TRACK=1`

ClamAV runtime updates are disabled with:

- `CLAMAV_NO_FRESHCLAMD=true`

## Prewarm Before Airgap

Before moving a deployment into an airgapped environment, prepare the required images and model caches in a connected environment:

- vLLM models in the `vllm-model-cache` volume under `/models/huggingface`
- FastEmbed sparse and cross-encoder reranker models in the host folder
  `model-cache/fastembed`, mounted into containers at `/models/fastembed`
- Docling artifacts and RapidOCR model files in the host folder
  `model-cache/docling`, mounted into containers at `/models/docling`
- ClamAV database packaged in the image or provided by an internal update process

The recommended Docling flow is runtime seeding into the persistent cache
folder, not build-time image downloads. Keep `PREWARM_DOCLING=false` for
repeatable offline rebuilds, then seed the shared cache once while connected:

```sh
docker compose build ingestion-worker
docker compose --profile prewarm run --rm docling-prewarm
```

The `docling-prewarm` service writes into `model-cache/docling`, and
`ingestion-worker` mounts that same folder at `/models/docling`. The prewarm
command downloads Docling layout/table artifacts plus RapidOCR OCR files and
verifies the cache before exiting. After seeding completes, the ingestion worker
can be rebuilt and restarted offline without re-downloading Docling or OCR
artifacts.

Runtime OCR is pinned to local RapidOCR by default:

- `DOCLING_OCR_BACKEND=onnxruntime`
- `DOCLING_OCR_LANGS=english`

Set `DOCLING_OCR_LANGS=chinese` or a comma-separated list such as
`english,chinese` before prewarming if that deployment needs a different
RapidOCR language set.

Build-time prewarm remains optional and network-capable. Runtime containers should not download.

FastEmbed sparse/reranker models are seeded into `model-cache/fastembed` or the
airgap bundle cache with:

```sh
python -m rag.ops.prewarm_fastembed
```

To cache every supported reranker before disconnecting:

```sh
python -m rag.ops.prewarm_fastembed --all-rerankers
```

The same command supports offline verification:

```sh
python -m rag.ops.prewarm_fastembed --verify-only
python -m rag.ops.prewarm_fastembed --verify-only --all-rerankers
```

By default this verifies `RAG_SPARSE_MODEL=Qdrant/bm25` and
`RAG_RERANKER_MODEL=jinaai/jina-reranker-v1-turbo-en` in `/models/fastembed`.
`--all-rerankers` verifies every model listed by the backend as supported.

## Optional vLLM Startup

The `vllm-text`, `vllm-embeddings`, and `vllm-vision` services are profile-gated under `vllm`. A normal stack start does not launch them:

```sh
docker compose up -d
```

When you are ready to enable them on a smaller setup, start only the profile-gated services you need:

```sh
docker compose --profile vllm up -d vllm-text vllm-embeddings vllm-vision
```

Keep the active backend/workspace RAG provider on `ollama` until those services are running and ready. Switching provider to `vllm` before that will leave the app pointing at unavailable endpoints.

## Apply Runtime Env Without Downloads

To apply offline env changes to already-running containers without rebuilding or pulling images:

```sh
docker compose up -d --no-build --force-recreate --no-deps api artifact-sandbox artifact-worker evaluation-worker folder-scheduler ingest-maintenance ingestion-worker clamav
```

This is not a hard network isolation boundary. For strict airgap enforcement, also block container egress at the host/network layer.
