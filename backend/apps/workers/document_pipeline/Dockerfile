# syntax=docker/dockerfile:1

FROM python:3.12-slim

ARG PYTORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/src
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=5
ENV SERVICE_NAME=ingestion-worker
ENV SERVICE_KIND=rag-ingestion-worker-celery
ENV RAG_MODEL_PROVIDER=ollama
ENV RAG_EMBEDDING_PROVIDER=fastembed
ENV RAG_FASTEMBED_MODEL=nomic-ai/nomic-embed-text-v1.5-Q
ENV RAG_DENSE_CACHE_DIR=/models/fastembed
ENV RAG_SPARSE_MODEL=Qdrant/bm25
ENV RAG_SPARSE_CACHE_DIR=/models/fastembed
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434
ENV OLLAMA_CHAT_MODEL=llama3.1:8b
ENV OLLAMA_EMBED_MODEL=nomic-embed-text:latest
ENV ENABLE_MOCK_MODELS=false

WORKDIR /app
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libxcb1 \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /models/fastembed /models/docling /models/huggingface \
    && chown -R appuser:appuser /models

COPY apps/workers/document_pipeline/pyproject.toml apps/workers/document_pipeline/constraints.txt /app/apps/workers/document_pipeline/
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --index-url "$PYTORCH_CPU_INDEX_URL" \
        "torch==2.12.0" "torchvision==0.27.0" \
    && python -c 'import tomllib; data=tomllib.load(open("/app/apps/workers/document_pipeline/pyproject.toml","rb")); print("\n".join(data["project"]["dependencies"]))' > /tmp/worker-requirements.txt \
    && python -m pip install -c /app/apps/workers/document_pipeline/constraints.txt -r /tmp/worker-requirements.txt \
    && rm /tmp/worker-requirements.txt

ENV DOCLING_ARTIFACTS_PATH=/models/docling
ENV DOCLING_OCR_BACKEND=onnxruntime
ENV DOCLING_OCR_LANGS=english
ENV HF_HUB_DISABLE_XET=1

COPY src/rag/ingestion /app/src/rag/ingestion
COPY src/rag/__init__.py /app/src/rag/__init__.py
COPY src/rag/graphrag /app/src/rag/graphrag
COPY src/rag/shared /app/src/rag/shared
COPY apps/__init__.py /app/apps/__init__.py
COPY apps/workers/__init__.py /app/apps/workers/__init__.py
COPY apps/workers/document_pipeline /app/apps/workers/document_pipeline
ARG PREWARM_FASTEMBED=false
ARG PREWARM_DOCLING=false
RUN if [ "$PREWARM_FASTEMBED" = "true" ]; then \
        python -c "import os; from fastembed import TextEmbedding, SparseTextEmbedding; TextEmbedding(os.getenv('RAG_FASTEMBED_MODEL', 'nomic-ai/nomic-embed-text-v1.5-Q'), cache_dir='/models/fastembed'); SparseTextEmbedding(os.getenv('RAG_SPARSE_MODEL', 'Qdrant/bm25'), cache_dir='/models/fastembed')"; \
    fi
RUN python -c 'from pathlib import Path; import rapidocr; path = Path(rapidocr.__file__).resolve().parent / "models"; path.mkdir(parents=True, exist_ok=True); print(path)' > /tmp/rapidocr_models_path \
    && chown -R appuser:appuser "$(cat /tmp/rapidocr_models_path)" /models/fastembed \
    && rm /tmp/rapidocr_models_path

USER appuser

RUN if [ "$PREWARM_DOCLING" = "true" ]; then \
        python -m rag.ingestion.ops.prewarm_docling; \
    fi

ENV AIRGAP_RUNTIME_OFFLINE=1
ENV HF_HOME=/models/huggingface
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV HF_DATASETS_OFFLINE=1
ENV HF_HUB_DISABLE_TELEMETRY=1
ENV HF_HUB_DISABLE_XET=1
ENV DO_NOT_TRACK=1

CMD ["celery", "-A", "apps.workers.document_pipeline.celery_app", "worker", "--loglevel=info"]
