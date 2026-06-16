# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/src \
    RAG_SPARSE_MODEL=Qdrant/bm25 \
    RAG_SPARSE_CACHE_DIR=/models/fastembed \
    RAG_RERANKER_MODEL=jinaai/jina-reranker-v1-turbo-en \
    RAG_RERANKER_CACHE_DIR=/models/fastembed

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml

ARG PREWARM_FASTEMBED=true

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice \
        poppler-utils \
        fonts-dejavu \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /models/fastembed /models/huggingface /work

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -c 'import tomllib; data=tomllib.load(open("/app/pyproject.toml","rb")); print("\n".join(data["project"]["dependencies"]))' > /tmp/backend-requirements.txt \
    && python -m pip install -r /tmp/backend-requirements.txt \
    && rm /tmp/backend-requirements.txt

COPY src /app/src
COPY apps/__init__.py /app/apps/__init__.py
COPY apps/api /app/apps/api

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --no-deps /app \
    && if [ "$PREWARM_FASTEMBED" = "true" ]; then \
        python -c "from fastembed import SparseTextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; SparseTextEmbedding('Qdrant/bm25', cache_dir='/models/fastembed'); TextCrossEncoder('jinaai/jina-reranker-v1-turbo-en', cache_dir='/models/fastembed')"; \
    fi \
    && chown -R appuser:appuser /models /work

ENV AIRGAP_RUNTIME_OFFLINE=1 \
    HF_HOME=/models/huggingface \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_XET=1 \
    DO_NOT_TRACK=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
