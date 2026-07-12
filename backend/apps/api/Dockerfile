# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/src \
    RAG_EMBEDDING_PROVIDER=fastembed \
    RAG_FASTEMBED_MODEL=nomic-ai/nomic-embed-text-v1.5-Q \
    RAG_DENSE_CACHE_DIR=/models/fastembed \
    RAG_SPARSE_MODEL=Qdrant/bm25 \
    RAG_SPARSE_CACHE_DIR=/models/fastembed \
    RAG_RERANKER_MODEL=jinaai/jina-reranker-v1-turbo-en \
    RAG_RERANKER_CACHE_DIR=/models/fastembed

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml

ARG PREWARM_FASTEMBED=false

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        libreoffice \
        poppler-utils \
        fonts-dejavu \
        libgssapi-krb5-2 \
        docker-cli \
        docker-compose \
    && . /etc/os-release \
    && debian_version="${VERSION_ID%%.*}" \
    && curl -fSL -o packages-microsoft-prod.deb "https://packages.microsoft.com/config/debian/${debian_version}/packages-microsoft-prod.deb" \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get install -y --no-install-recommends \
        unixodbc \
        unixodbc-dev \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /models/fastembed /models/huggingface /work

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -c 'import tomllib; data=tomllib.load(open("/app/pyproject.toml","rb")); print("\n".join(data["project"]["dependencies"]))' > /tmp/backend-requirements.txt \
    && python -m pip install -r /tmp/backend-requirements.txt \
    && rm /tmp/backend-requirements.txt

COPY src /app/src
COPY apps/__init__.py /app/apps/__init__.py
COPY apps/api /app/apps/api
COPY apps/workers/__init__.py /app/apps/workers/__init__.py
COPY apps/workers/artifact /app/apps/workers/artifact
COPY apps/workers/evaluation /app/apps/workers/evaluation
COPY apps/background /app/apps/background

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --no-deps /app \
    && if [ "$PREWARM_FASTEMBED" = "true" ]; then \
        python -m rag.ops.prewarm_fastembed; \
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

HEALTHCHECK --interval=10s --timeout=10s --retries=5 --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=8)"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
