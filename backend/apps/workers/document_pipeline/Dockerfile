# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.12 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/src
ENV PATH=/opt/venv/bin:$PATH
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_HTTP_TIMEOUT=120
ENV UV_HTTP_RETRIES=5

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

COPY apps/workers/document_pipeline/pyproject.toml apps/workers/document_pipeline/uv.lock /app/apps/workers/document_pipeline/
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync \
        --project /app/apps/workers/document_pipeline \
        --locked \
        --no-dev \
        --no-install-project

ENV DOCLING_ARTIFACTS_PATH=/models/docling
ENV DOCLING_OCR_BACKEND=onnxruntime
ENV DOCLING_OCR_LANGS=english

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
        python -c "from fastembed import TextEmbedding, SparseTextEmbedding; from rag.shared.contracts.rag_defaults import DEFAULT_FASTEMBED_CACHE_DIR, DEFAULT_FASTEMBED_DENSE_MODEL, DEFAULT_SPARSE_MODEL; TextEmbedding(DEFAULT_FASTEMBED_DENSE_MODEL, cache_dir=DEFAULT_FASTEMBED_CACHE_DIR); SparseTextEmbedding(DEFAULT_SPARSE_MODEL, cache_dir=DEFAULT_FASTEMBED_CACHE_DIR)"; \
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
