"""Scheduled query analytics retention with a healthchecked success heartbeat."""

import argparse
import logging
import time
from dataclasses import asdict

from apps.background.watchdog import HEARTBEAT_PATH, heartbeat, is_fresh
from rag.core.config import settings
from rag.ops.query_analytics_maintenance import run_once

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    interval = settings.query_analytics_maintenance_interval_seconds
    if args.healthcheck:
        return 0 if is_fresh(HEARTBEAT_PATH, 3 * interval) else 1
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            result = run_once()
            heartbeat()
            logger.info("query analytics maintenance %s", asdict(result))
        except Exception as exc:  # noqa: BLE001 - retry on the next cycle, with a stale healthcheck
            logger.error("query analytics maintenance failed: %s", type(exc).__name__)
            if args.once:
                raise
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
