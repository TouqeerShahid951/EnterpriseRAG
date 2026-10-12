"""Reconcile expired execution heartbeats and expire retained query analytics."""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime, timedelta

from rag.core.config import settings
from rag.query.analytics.models import AnalyticsMaintenanceResult
from rag.query.analytics.repository import get_analytics_repository


logger = logging.getLogger("rag.query_analytics_maintenance")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.loop and not args.once:
        args.once = True

    while True:
        try:
            result = run_once()
            logger.info(
                "query analytics maintenance reconciled=%d deleted_executions=%d "
                "deleted_boundary_events=%d expired_lineage=%d",
                result.reconciled_execution_count,
                result.deleted_execution_count,
                result.deleted_boundary_event_count,
                result.expired_lineage_count,
            )
        except Exception:  # noqa: BLE001 - loop mode must keep the scheduler alive
            logger.exception("query analytics maintenance failed")
            if not args.loop:
                raise
        if not args.loop:
            return
        time.sleep(settings.query_analytics_maintenance_interval_seconds)


def run_once(*, as_of: datetime | None = None) -> AnalyticsMaintenanceResult:
    now = as_of or datetime.now(UTC)
    return get_analytics_repository().maintain(
        as_of=now,
        retention_before=now - timedelta(days=settings.query_analytics_retention_days),
        lineage_before=now - timedelta(days=settings.query_analytics_lineage_retention_days),
        batch_size=settings.query_analytics_maintenance_batch_size,
        reconcile=True,
    )


if __name__ == "__main__":
    main()
