# Airgap Runtime Mode

AgenticRAG runtime containers default to offline model loading. Runtime code should fail fast when a required model or artifact is missing instead of downloading it.

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
- FastEmbed sparse/reranker models in the `backend-reranker-cache` volume under `/models/fastembed`
- Docling artifacts in the `backend-docling-cache` volume under `/models/docling`
- ClamAV database packaged in the image or provided by an internal update process

The recommended Docling flow is runtime seeding into the persistent volume, not build-time image downloads. Keep `PREWARM_DOCLING=false` for repeatable offline rebuilds, then seed the shared cache once while connected:

```sh
docker compose build ingestion-worker
docker compose --profile prewarm run --rm docling-prewarm
```

The `docling-prewarm` service writes into `backend-docling-cache`, and `ingestion-worker` mounts that same volume at `/models/docling`. After seeding completes, the ingestion worker can be rebuilt and restarted offline without re-downloading Docling artifacts.

Build-time prewarm remains optional and network-capable. Runtime containers should not download.

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
