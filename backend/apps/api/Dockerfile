# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.12 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/src \
    PATH=/opt/venv/bin:$PATH \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=5

WORKDIR /app

COPY pyproject.toml uv.lock /app/

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

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-dev --no-install-project

COPY src /app/src
COPY apps/__init__.py /app/apps/__init__.py
COPY apps/api /app/apps/api
COPY apps/workers/__init__.py /app/apps/workers/__init__.py
COPY apps/workers/artifact /app/apps/workers/artifact
COPY apps/workers/evaluation /app/apps/workers/evaluation
COPY apps/background /app/apps/background

RUN if [ "$PREWARM_FASTEMBED" = "true" ]; then \
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
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=8)"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
