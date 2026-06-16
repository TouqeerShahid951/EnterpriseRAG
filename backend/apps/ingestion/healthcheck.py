"""Container healthcheck for the Celery ingestion worker."""

from __future__ import annotations

import sys

from rag_ingestion.config import WorkerConfig


def main() -> int:
    try:
        config = WorkerConfig.from_env()
        from redis import Redis

        Redis.from_url(config.redis_url).ping()
    except Exception as exc:
        print(f"worker healthcheck failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
