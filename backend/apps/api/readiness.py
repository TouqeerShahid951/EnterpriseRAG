"""Bounded readiness probes for dependencies required by the API process."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

from rag.core.config import settings
from rag.query.configuration.models import ACTIVE_CONFIG_KEY, RagConfigRecord
from rag.query.configuration.repository import effective_rag_config
from rag.query.configuration.validation import env_rag_config, record_from_row
from rag.shared.fastembed_cache import (
    RERANKER_REQUIRED_SNAPSHOT_FILES,
    has_complete_fastembed_model_cache,
    has_fastembed_model_cache,
)

_PROBE_TIMEOUT_SECONDS = 2


def probe_readiness() -> tuple[str, ...]:
    """Return stable dependency names for probes that fail."""

    with ThreadPoolExecutor(max_workers=3) as executor:
        config_future = executor.submit(_load_effective_rag_config)
        redis_future = executor.submit(_failed_dependency, ("redis", _check_redis))
        qdrant_future = executor.submit(_failed_dependency, ("qdrant", _check_qdrant))
        try:
            rag_config = config_future.result()
            postgres_failure = None
        except Exception:
            rag_config = None
            postgres_failure = "postgres"
        failures = [postgres_failure, redis_future.result(), qdrant_future.result()]
    if rag_config is not None:
        failures.append(
            _failed_dependency(("model_cache", lambda: _check_model_cache(rag_config)))
        )
    return tuple(name for name in failures if name is not None)


def _failed_dependency(check: tuple[str, Callable[[], None]]) -> str | None:
    name, probe = check
    try:
        probe()
    except Exception:
        return name
    return None


def _load_effective_rag_config() -> RagConfigRecord:
    if settings.document_repository == "memory":
        return effective_rag_config(config=settings)

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(
        settings.database_url,
        connect_timeout=_PROBE_TIMEOUT_SECONDS,
        options=f"-c statement_timeout={_PROBE_TIMEOUT_SECONDS * 1000}",
        row_factory=dict_row,
    ) as connection:
        row = connection.execute(
            "SELECT * FROM workspace_rag_config WHERE config_key = %s",
            (ACTIVE_CONFIG_KEY,),
        ).fetchone()
    return record_from_row(row) if row else env_rag_config(settings)


def _check_redis() -> None:
    from redis import Redis

    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=_PROBE_TIMEOUT_SECONDS,
        socket_timeout=_PROBE_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()


def _check_qdrant() -> None:
    with urlopen(  # noqa: S310 - the URL is trusted deployment configuration.
        f"{settings.qdrant_url.rstrip('/')}/readyz",
        timeout=_PROBE_TIMEOUT_SECONDS,
    ) as response:
        response.read(1)


def _check_model_cache(rag_config: RagConfigRecord) -> None:
    if rag_config.embedding_provider == "fastembed" and not has_fastembed_model_cache(
        settings.rag_dense_cache_dir,
        rag_config.embed_model,
    ):
        raise RuntimeError("dense model cache unavailable")
    if not has_fastembed_model_cache(
        settings.rag_sparse_cache_dir,
        settings.rag_sparse_model,
    ):
        raise RuntimeError("sparse model cache unavailable")
    if not has_complete_fastembed_model_cache(
        settings.rag_reranker_cache_dir,
        rag_config.reranker_model,
        required_files=RERANKER_REQUIRED_SNAPSHOT_FILES,
    ):
        raise RuntimeError("reranker model cache unavailable")
