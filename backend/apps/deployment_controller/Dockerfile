# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-cli \
        docker-compose \
    && rm -rf /var/lib/apt/lists/*

COPY src/rag/__init__.py /app/rag/__init__.py
COPY src/rag/deployment /app/rag/deployment
COPY apps/__init__.py /app/apps/__init__.py
COPY apps/deployment_controller /app/apps/deployment_controller

EXPOSE 8080

CMD ["python", "-m", "apps.deployment_controller.main"]
